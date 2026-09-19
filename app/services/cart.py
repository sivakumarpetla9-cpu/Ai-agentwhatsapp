from decimal import Decimal
from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, EntityNotFoundError
from app.models.customer import CustomerSession
from app.models.cart import Cart, CartItem
from app.repositories.cart import CartItemRepository, CartRepository
from app.repositories.customer import CustomerSessionRepository
from app.repositories.menu import MenuItemRepository
from app.repositories.restaurant import RestaurantRepository
from app.schemas.cart import CartItemResponse, CartResponse
from app.services.base import BaseService


class CartService(BaseService):
    """
    Service handling customer shopping cart lifecycle, price snapshotting, and item management.
    Strictly scoped to the customer's active session.
    """
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.session_repo = CustomerSessionRepository(session)
        self.restaurant_repo = RestaurantRepository(session)
        self.menu_item_repo = MenuItemRepository(session)
        self.cart_repo = CartRepository(session)
        self.cart_item_repo = CartItemRepository(session)

    async def _validate_and_get_session(self, session_id: UUID) -> CustomerSession:
        """
        Ensure session is valid, active, unexpired, and associated with an active restaurant.
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

    def _build_cart_response(self, cart: Cart) -> CartResponse:
        """
        Assemble CartResponse with exact Decimal calculations.
        """
        items_response = [
            CartItemResponse(
                id=item.id,
                menu_item_id=item.menu_item_id,
                name=item.menu_item.name if item.menu_item else "Unknown Item",
                quantity=item.quantity,
                unit_price=item.unit_price,
                line_total=item.line_total,
            )
            for item in cart.items
        ]

        return CartResponse(
            cart_id=cart.id,
            session_id=cart.customer_session_id,
            items=items_response,
            subtotal=cart.subtotal,
            item_count=cart.item_count,
        )

    async def get_cart(self, session_id: UUID) -> CartResponse:
        """
        Retrieve or initialize the active cart for the customer session.
        """
        await self._validate_and_get_session(session_id)
        cart = await self.cart_repo.get_or_create_active_cart(session_id)
        refreshed_cart = await self.cart_repo.get_active_cart_for_session(session_id)
        return self._build_cart_response(refreshed_cart or cart)

    async def add_item(
        self, session_id: UUID, menu_item_id: UUID, quantity: int
    ) -> CartResponse:
        """
        Add an item to the active cart with commercial price snapshotting.
        Enforces that quantity > 0, item is available, and item belongs to the session's restaurant.
        """
        if quantity <= 0:
            raise BadRequestError(
                message="Quantity must be greater than zero.",
                error_code="INVALID_QUANTITY",
            )

        customer_session = await self._validate_and_get_session(session_id)

        # 1. Fetch menu item and validate ownership
        menu_item = await self.menu_item_repo.get_by_id(menu_item_id)
        if not menu_item:
            raise EntityNotFoundError(
                message=f"Menu item '{menu_item_id}' not found.",
                error_code="ITEM_NOT_FOUND",
            )

        if menu_item.restaurant_id != customer_session.restaurant_id:
            raise BadRequestError(
                message="Cannot add menu item belonging to another restaurant.",
                error_code="CROSS_RESTAURANT_ITEM_REJECTED",
            )

        if not menu_item.is_available:
            raise BadRequestError(
                message=f"'{menu_item.name}' is currently unavailable.",
                error_code="ITEM_UNAVAILABLE",
            )

        if menu_item.category and not menu_item.category.is_active:
            raise BadRequestError(
                message=f"Category '{menu_item.category.name}' is currently inactive.",
                error_code="CATEGORY_INACTIVE",
            )

        # 2. Get or create active cart
        cart = await self.cart_repo.get_or_create_active_cart(session_id)

        # 3. Snapshot unit price and add/increment item
        unit_price = menu_item.price
        await self.cart_item_repo.add_or_increment(
            cart_id=cart.id,
            menu_item_id=menu_item.id,
            quantity=quantity,
            unit_price=unit_price,
        )

        # Re-fetch cart with populate_existing to update item collection
        refreshed_cart = await self.cart_repo.get_active_cart_for_session(session_id)
        return self._build_cart_response(refreshed_cart or cart)

    async def update_item_quantity(
        self, session_id: UUID, cart_item_id: UUID, quantity: int
    ) -> CartResponse:
        """
        Update item quantity in active cart. Quantity must be > 0.
        """
        if quantity <= 0:
            raise BadRequestError(
                message="Quantity must be greater than zero. Use DELETE to remove an item.",
                error_code="INVALID_QUANTITY",
            )

        await self._validate_and_get_session(session_id)
        cart = await self.cart_repo.get_active_cart_for_session(session_id)

        if not cart:
            raise EntityNotFoundError(
                message=f"Cart item '{cart_item_id}' not found in active cart.",
                error_code="CART_ITEM_NOT_FOUND",
            )

        cart_item = await self.cart_item_repo.get_by_id(cart_item_id)
        if not cart_item or cart_item.cart_id != cart.id:
            raise EntityNotFoundError(
                message=f"Cart item '{cart_item_id}' not found in this active cart.",
                error_code="CART_ITEM_NOT_FOUND",
            )

        cart_item.quantity = quantity
        await self.session.flush()

        refreshed_cart = await self.cart_repo.get_active_cart_for_session(session_id)
        return self._build_cart_response(refreshed_cart or cart)

    async def remove_item(self, session_id: UUID, cart_item_id: UUID) -> CartResponse:
        """
        Remove an item from the active cart.
        """
        await self._validate_and_get_session(session_id)
        cart = await self.cart_repo.get_active_cart_for_session(session_id)

        if not cart:
            raise EntityNotFoundError(
                message=f"Cart item '{cart_item_id}' not found in active cart.",
                error_code="CART_ITEM_NOT_FOUND",
            )

        cart_item = await self.cart_item_repo.get_by_id(cart_item_id)
        if not cart_item or cart_item.cart_id != cart.id:
            raise EntityNotFoundError(
                message=f"Cart item '{cart_item_id}' not found in this active cart.",
                error_code="CART_ITEM_NOT_FOUND",
            )

        await self.cart_item_repo.delete(cart_item)

        refreshed_cart = await self.cart_repo.get_active_cart_for_session(session_id)
        return self._build_cart_response(refreshed_cart or cart)

    async def clear_cart(self, session_id: UUID) -> CartResponse:
        """
        Remove all items from the active cart while keeping the cart record.
        """
        await self._validate_and_get_session(session_id)
        cart = await self.cart_repo.get_active_cart_for_session(session_id)

        if cart:
            await self.cart_item_repo.clear_cart_items(cart)
            refreshed_cart = await self.cart_repo.get_active_cart_for_session(session_id)
            return self._build_cart_response(refreshed_cart or cart)

        cart = await self.cart_repo.get_or_create_active_cart(session_id)
        return self._build_cart_response(cart)
