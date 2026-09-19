import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional
from uuid import UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import BadRequestError, EntityNotFoundError
from app.models.bill import Bill, BillItem, BillStatus, generate_bill_number
from app.models.customer import CustomerSession
from app.models.order import OrderStatus
from app.repositories.bill import BillItemRepository, BillRepository
from app.repositories.cart import CartRepository
from app.repositories.customer import CustomerSessionRepository
from app.repositories.order import OrderRepository
from app.repositories.restaurant import RestaurantRepository, RestaurantTableRepository
from app.schemas.billing import BillItemResponse, BillResponse
from app.services.base import BaseService

logger = logging.getLogger("whatsapp_ordering.services.billing")
settings = get_settings()

UNRESOLVED_STATUSES = {
    OrderStatus.NEW.value,
    OrderStatus.ACCEPTED.value,
    OrderStatus.PREPARING.value,
    OrderStatus.READY.value,
}


class BillingService(BaseService):
    """
    Dedicated billing service consolidating all valid dining orders across multiple rounds
    into a single persistent session Bill. Handles tax calculations, idempotency,
    and final session settlement.
    """
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.session_repo = CustomerSessionRepository(session)
        self.restaurant_repo = RestaurantRepository(session)
        self.table_repo = RestaurantTableRepository(session)
        self.cart_repo = CartRepository(session)
        self.order_repo = OrderRepository(session)
        self.bill_repo = BillRepository(session)
        self.bill_item_repo = BillItemRepository(session)

    async def _validate_and_get_session(self, session_id: UUID) -> CustomerSession:
        """
        Validate that the dining session exists and the restaurant is currently active.
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

    def _build_bill_response(self, bill: Bill) -> BillResponse:
        """
        Construct privacy-safe BillResponse. Never exposes customer WhatsApp identifier.
        """
        items_response = [
            BillItemResponse(
                id=item.id,
                order_id=item.order_id,
                order_item_id=item.order_item_id,
                item_name_snapshot=item.item_name_snapshot,
                quantity=item.quantity,
                unit_price=item.unit_price,
                line_total=item.line_total,
            )
            for item in bill.items
        ]

        table_number = bill.table.table_number if bill.table else "Table"

        return BillResponse(
            id=bill.id,
            bill_number=bill.bill_number,
            restaurant_id=bill.restaurant_id,
            table_id=bill.table_id,
            table_number=table_number,
            session_id=bill.session_id,
            orders_included=bill.orders_included,
            items=items_response,
            subtotal=bill.subtotal,
            tax_amount=bill.tax_amount,
            grand_total=bill.grand_total,
            status=bill.status,
            created_at=bill.created_at,
            settled_at=bill.settled_at,
        )

    async def generate_or_get_bill(self, session_id: UUID) -> BillResponse:
        """
        Idempotently create or retrieve the OPEN consolidated bill for an active session.
        Consolidates only SERVED orders. Cancelled orders are excluded.
        If new orders have been served since bill generation, syncs them into the OPEN bill.
        """
        customer_session = await self._validate_and_get_session(session_id)

        # Retrieve all session orders
        orders = await self.order_repo.get_orders_by_session(session_id)
        billable_orders = [ord for ord in orders if ord.status == OrderStatus.SERVED.value]

        # Check for existing OPEN bill
        open_bill = await self.bill_repo.get_open_bill_by_session(session_id)

        if not billable_orders and not open_bill:
            raise BadRequestError(
                message="No billable orders found for this session.",
                error_code="NO_BILLABLE_ORDERS",
            )

        tax_rate = Decimal(str(settings.BILL_TAX_RATE))

        if open_bill:
            # Sync any newly served order items into existing open bill
            existing_order_item_ids = {item.order_item_id for item in open_bill.items}
            items_added = False

            for order in billable_orders:
                for ord_item in order.items:
                    if ord_item.id not in existing_order_item_ids:
                        new_item = BillItem(
                            bill_id=open_bill.id,
                            order_id=order.id,
                            order_item_id=ord_item.id,
                            item_name_snapshot=ord_item.item_name,
                            quantity=ord_item.quantity,
                            unit_price=ord_item.unit_price,
                            line_total=ord_item.line_total,
                        )
                        self.session.add(new_item)
                        items_added = True

            if items_added:
                await self.session.flush()
                # Recalculate bill monetary totals
                fresh_bill = await self.bill_repo.get_by_id(open_bill.id)
                assert fresh_bill is not None
                subtotal = sum((itm.line_total for itm in fresh_bill.items), Decimal("0.00")).quantize(Decimal("0.01"))
                tax_amount = (subtotal * tax_rate).quantize(Decimal("0.01"))
                grand_total = (subtotal + tax_amount).quantize(Decimal("0.01"))

                fresh_bill.subtotal = subtotal
                fresh_bill.tax_amount = tax_amount
                fresh_bill.grand_total = grand_total
                await self.session.flush()
                return self._build_bill_response(fresh_bill)

            return self._build_bill_response(open_bill)

        # No open bill exists: calculate totals from billable orders
        subtotal = sum(
            (itm.line_total for ord in billable_orders for itm in ord.items),
            Decimal("0.00"),
        ).quantize(Decimal("0.01"))
        tax_amount = (subtotal * tax_rate).quantize(Decimal("0.01"))
        grand_total = (subtotal + tax_amount).quantize(Decimal("0.01"))

        bill = Bill(
            bill_number=generate_bill_number(),
            restaurant_id=customer_session.restaurant_id,
            table_id=customer_session.table_id,
            session_id=customer_session.id,
            subtotal=subtotal,
            tax_amount=tax_amount,
            grand_total=grand_total,
            status=BillStatus.OPEN.value,
        )
        self.session.add(bill)

        try:
            await self.session.flush()
        except IntegrityError:
            # Handle race condition where two bill requests arrived concurrently
            await self.session.rollback()
            existing = await self.bill_repo.get_open_bill_by_session(session_id)
            if existing:
                return self._build_bill_response(existing)
            raise

        # Snapshot order items into bill items
        for order in billable_orders:
            for ord_item in order.items:
                bill_item = BillItem(
                    bill_id=bill.id,
                    order_id=order.id,
                    order_item_id=ord_item.id,
                    item_name_snapshot=ord_item.item_name,
                    quantity=ord_item.quantity,
                    unit_price=ord_item.unit_price,
                    line_total=ord_item.line_total,
                )
                self.session.add(bill_item)

        await self.session.flush()
        fresh_bill = await self.bill_repo.get_by_id(bill.id)
        logger.info(f"Generated bill '{bill.bill_number}' for session '{session_id}' (Total: {grand_total})")
        return self._build_bill_response(fresh_bill or bill)

    async def get_bill_by_session(self, session_id: UUID) -> BillResponse:
        """
        Retrieve current/latest bill for a dining session.
        """
        await self._validate_and_get_session(session_id)
        bill = await self.bill_repo.get_latest_bill_by_session(session_id)
        if not bill:
            raise EntityNotFoundError(
                message="No bill found for this session.",
                error_code="BILL_NOT_FOUND",
            )
        return self._build_bill_response(bill)

    async def settle_bill(
        self,
        bill_id: UUID,
        restaurant_id: Optional[UUID] = None,
        session_id: Optional[UUID] = None,
    ) -> BillResponse:
        """
        Perform final session settlement:
        1. Validates tenant and session ownership.
        2. Validates bill is OPEN and not already settled.
        3. Enforces settlement safety: rejects if ANY session order is unresolved.
        4. Transitions Bill: OPEN -> SETTLED (records settled_at).
        5. Transitions CustomerSession: ACTIVE -> CLOSED (frees the table).
        6. Archives active Cart: ACTIVE -> ARCHIVED.
        Historical order and bill records remain queryable.
        """
        bill = await self.bill_repo.get_by_id(bill_id)
        if not bill:
            raise EntityNotFoundError(
                message=f"Bill '{bill_id}' not found.",
                error_code="BILL_NOT_FOUND",
            )

        # Multi-tenant and session scoping verification
        if restaurant_id and bill.restaurant_id != restaurant_id:
            raise EntityNotFoundError(
                message=f"Bill '{bill_id}' not found for this restaurant.",
                error_code="BILL_NOT_FOUND",
            )
        if session_id and bill.session_id != session_id:
            raise EntityNotFoundError(
                message=f"Bill '{bill_id}' not found for this session.",
                error_code="BILL_NOT_FOUND",
            )

        # Check double-settlement
        if bill.status == BillStatus.SETTLED.value:
            raise BadRequestError(
                message="Bill is already settled.",
                error_code="BILL_ALREADY_SETTLED",
            )
        if bill.status != BillStatus.OPEN.value:
            raise BadRequestError(
                message=f"Cannot settle bill with status '{bill.status}'.",
                error_code="INVALID_BILL_STATUS",
            )

        # IMPORTANT SETTLEMENT SAFETY: Verify no unresolved orders exist in the session
        session_orders = await self.order_repo.get_orders_by_session(bill.session_id)
        unresolved_orders = [ord for ord in session_orders if ord.status in UNRESOLVED_STATUSES]
        if unresolved_orders:
            unresolved_nums = ", ".join(o.order_number for o in unresolved_orders)
            raise BadRequestError(
                message=f"Cannot settle table while there are unresolved orders: {unresolved_nums}.",
                error_code="UNRESOLVED_ORDERS",
            )

        # 1. Mark Bill SETTLED
        bill.status = BillStatus.SETTLED.value
        bill.settled_at = datetime.now(timezone.utc)

        # 2. Close CustomerSession (releases table for new diners)
        if bill.session:
            bill.session.status = "CLOSED"
        else:
            customer_session = await self.session_repo.get_by_id(bill.session_id)
            if customer_session:
                customer_session.status = "CLOSED"

        # 3. Archive active Cart
        if bill.session and bill.session.cart:
            bill.session.cart.status = "ARCHIVED"
        else:
            cart = await self.cart_repo.get_active_cart_for_session(bill.session_id)
            if cart:
                cart.status = "ARCHIVED"

        await self.session.flush()
        logger.info(f"Bill '{bill.bill_number}' successfully settled. Session '{bill.session_id}' closed.")

        return self._build_bill_response(bill)
