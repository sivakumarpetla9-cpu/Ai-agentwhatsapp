import logging
from typing import List, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, EntityNotFoundError
from app.models.customer import CustomerSession
from app.models.order import (
    ALLOWED_TRANSITIONS,
    Order,
    OrderItem,
    OrderStatus,
    generate_order_number,
)
from app.repositories.cart import CartItemRepository, CartRepository
from app.repositories.customer import CustomerSessionRepository
from app.repositories.order import OrderItemRepository, OrderRepository
from app.repositories.restaurant import RestaurantRepository
from app.schemas.order import (
    KitchenOrderResponse,
    OrderItemResponse,
    OrderResponse,
)
from app.services.base import BaseService

logger = logging.getLogger("whatsapp_ordering.services.order")


class OrderService(BaseService):
    """
    Service managing order creation from active customer carts and
    kitchen lifecycle state transitions (NEW -> ACCEPTED -> PREPARING -> READY -> SERVED).
    """
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.session_repo = CustomerSessionRepository(session)
        self.restaurant_repo = RestaurantRepository(session)
        self.cart_repo = CartRepository(session)
        self.cart_item_repo = CartItemRepository(session)
        self.order_repo = OrderRepository(session)
        self.order_item_repo = OrderItemRepository(session)

    async def _validate_and_get_session(self, session_id: UUID) -> CustomerSession:
        """
        Ensure dining session exists, is active, unexpired, and restaurant is open.
        """
        customer_session = await self.session_repo.get_by_id(session_id)
        if not customer_session:
            raise EntityNotFoundError(
                message=f"Session '{session_id}' not found.",
                error_code="SESSION_NOT_FOUND",
            )

        if not customer_session.is_currently_active:
            raise BadRequestError(
                message="Session has expired or is no longer active.",
                error_code="SESSION_EXPIRED",
            )

        restaurant = await self.restaurant_repo.get_by_id(customer_session.restaurant_id)
        if not restaurant or not restaurant.is_active:
            raise BadRequestError(
                message="The restaurant for this session is currently closed or inactive.",
                error_code="RESTAURANT_INACTIVE",
            )

        return customer_session

    def _build_order_response(self, order: Order) -> OrderResponse:
        """
        Build public customer order response. Never exposes customer PII.
        """
        items_response = [
            OrderItemResponse(
                id=item.id,
                menu_item_id=item.menu_item_id,
                item_name=item.item_name,
                quantity=item.quantity,
                unit_price=item.unit_price,
                line_total=item.line_total,
            )
            for item in order.items
        ]

        table_number = order.table.table_number if order.table else "Table"

        return OrderResponse(
            id=order.id,
            order_number=order.order_number,
            session_id=order.customer_session_id,
            restaurant_id=order.restaurant_id,
            table_id=order.table_id,
            table_number=table_number,
            status=order.status,
            total_amount=order.total_amount,
            item_count=order.item_count,
            special_instructions=order.special_instructions,
            items=items_response,
            created_at=order.created_at,
            updated_at=order.updated_at,
        )

    def _build_kitchen_response(self, order: Order) -> KitchenOrderResponse:
        """
        Build kitchen display order representation.
        """
        items_response = [
            OrderItemResponse(
                id=item.id,
                menu_item_id=item.menu_item_id,
                item_name=item.item_name,
                quantity=item.quantity,
                unit_price=item.unit_price,
                line_total=item.line_total,
            )
            for item in order.items
        ]

        table_number = order.table.table_number if order.table else "Table"

        return KitchenOrderResponse(
            id=order.id,
            order_number=order.order_number,
            table_number=table_number,
            status=order.status,
            item_count=order.item_count,
            total_amount=order.total_amount,
            special_instructions=order.special_instructions,
            items=items_response,
            created_at=order.created_at,
            updated_at=order.updated_at,
        )

    async def checkout_cart(
        self, session_id: UUID, special_instructions: Optional[str] = None
    ) -> OrderResponse:
        """
        Convert active customer cart into a placed Order in NEW status.
        Snapshots item names, quantities, and prices to guarantee price integrity.
        Empties the cart so the customer can place subsequent rounds during their session.
        """
        customer_session = await self._validate_and_get_session(session_id)

        # Retrieve active cart with row lock where supported
        cart = await self.cart_repo.get_active_cart_for_session(session_id, for_update=True)
        if not cart or not cart.items:
            raise BadRequestError(
                message="Cannot checkout an empty cart. Please add items before placing an order.",
                error_code="EMPTY_CART",
            )

        # Validate menu item availability at time of checkout
        for cart_item in cart.items:
            menu_item = cart_item.menu_item
            if not menu_item or not menu_item.is_available:
                name = menu_item.name if menu_item else "Item"
                raise BadRequestError(
                    message=f"'{name}' is currently unavailable and cannot be ordered.",
                    error_code="ITEM_UNAVAILABLE",
                )
            if menu_item.category and not menu_item.category.is_active:
                raise BadRequestError(
                    message=f"Category '{menu_item.category.name}' is inactive.",
                    error_code="CATEGORY_INACTIVE",
                )

        # Create Order in NEW status with snapshotted total
        order = Order(
            order_number=generate_order_number(),
            restaurant_id=customer_session.restaurant_id,
            table_id=customer_session.table_id,
            customer_session_id=customer_session.id,
            status=OrderStatus.NEW.value,
            total_amount=cart.subtotal,
            special_instructions=special_instructions.strip() if special_instructions else None,
        )
        self.session.add(order)
        await self.session.flush()

        # Snapshot cart items into OrderItem records
        for cart_item in cart.items:
            order_item = OrderItem(
                order_id=order.id,
                menu_item_id=cart_item.menu_item_id,
                item_name=cart_item.menu_item.name,
                quantity=cart_item.quantity,
                unit_price=cart_item.unit_price,
            )
            self.session.add(order_item)

        # Clear cart items so customer can begin fresh cart for next round
        await self.cart_item_repo.clear_cart_items(cart)
        await self.session.flush()

        # Re-fetch order to populate relationship collections
        fresh_order = await self.order_repo.get_by_id(order.id)
        logger.info(
            f"Order '{order.order_number}' placed successfully for table '{customer_session.table_id}'"
        )
        return self._build_order_response(fresh_order or order)

    async def get_session_orders(self, session_id: UUID) -> List[OrderResponse]:
        """
        List all orders placed within an active customer session.
        """
        await self._validate_and_get_session(session_id)
        orders = await self.order_repo.get_orders_by_session(session_id)
        return [self._build_order_response(order) for order in orders]

    async def get_order_for_session(
        self, session_id: UUID, order_id: UUID
    ) -> OrderResponse:
        """
        Retrieve order details strictly scoped to the customer's session.
        """
        await self._validate_and_get_session(session_id)
        order = await self.order_repo.get_by_id_and_session(order_id, session_id)
        if not order:
            raise EntityNotFoundError(
                message=f"Order '{order_id}' not found in this session.",
                error_code="ORDER_NOT_FOUND",
            )
        return self._build_order_response(order)

    async def get_kitchen_orders(
        self, restaurant_id: UUID, status: Optional[str] = None
    ) -> List[KitchenOrderResponse]:
        """
        Fetch kitchen display queue for a restaurant, optionally filtered by status.
        """
        restaurant = await self.restaurant_repo.get_by_id(restaurant_id)
        if not restaurant:
            raise EntityNotFoundError(
                message=f"Restaurant '{restaurant_id}' not found.",
                error_code="RESTAURANT_NOT_FOUND",
            )

        if status:
            status_clean = status.upper().strip()
            if status_clean not in OrderStatus.__members__:
                raise BadRequestError(
                    message=f"Invalid status filter '{status}'.",
                    error_code="INVALID_STATUS",
                )
            status = status_clean

        orders = await self.order_repo.get_orders_by_restaurant(restaurant_id, status)
        return [self._build_kitchen_response(order) for order in orders]

    async def transition_order_status(
        self, restaurant_id: UUID, order_id: UUID, new_status: str
    ) -> KitchenOrderResponse:
        """
        Advance order along the kitchen state machine:
        NEW -> ACCEPTED -> PREPARING -> READY -> SERVED (or CANCELLED).
        Strictly rejects invalid or out-of-order transitions.
        """
        # Validate target status value
        clean_status_str = new_status.upper().strip()
        try:
            target_status = OrderStatus(clean_status_str)
        except ValueError:
            raise BadRequestError(
                message=f"Invalid status '{new_status}'. Allowed: {[s.value for s in OrderStatus]}",
                error_code="INVALID_STATUS",
            )

        # Validate order exists for this restaurant
        order = await self.order_repo.get_by_id_and_restaurant(order_id, restaurant_id)
        if not order:
            raise EntityNotFoundError(
                message=f"Order '{order_id}' not found for restaurant '{restaurant_id}'.",
                error_code="ORDER_NOT_FOUND",
            )

        current_status = OrderStatus(order.status)

        # Validate transition via state machine rules
        allowed_next = ALLOWED_TRANSITIONS.get(current_status, [])
        if target_status not in allowed_next:
            allowed_str = ", ".join(s.value for s in allowed_next) or "None (terminal state)"
            raise BadRequestError(
                message=(
                    f"Cannot transition order from {current_status.value} to {target_status.value}. "
                    f"Allowed transitions from {current_status.value}: {allowed_str}."
                ),
                error_code="INVALID_STATUS_TRANSITION",
            )

        # Apply state transition
        order.status = target_status.value
        await self.session.flush()

        logger.info(
            f"Order '{order.order_number}' transitioned from {current_status.value} to {target_status.value}"
        )
        fresh_order = await self.order_repo.get_by_id(order.id)
        return self._build_kitchen_response(fresh_order or order)
