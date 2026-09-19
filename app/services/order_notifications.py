import logging
import re
from datetime import datetime, timezone
from typing import Dict, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.integrations.whatsapp.client import (
    BaseWhatsAppClient,
    WhatsAppClient,
    whatsapp_client as default_whatsapp_client,
)
from app.models.customer import CustomerSession
from app.models.order import Order, OrderStatus
from app.models.order_notification import OrderNotification
from app.repositories.notification import OrderNotificationRepository
from app.services.base import BaseService
from app.services.session import mask_identifier

logger = logging.getLogger("whatsapp_ordering.services.order_notifications")

STATUS_NOTIFICATION_TEMPLATES: Dict[str, str] = {
    OrderStatus.ACCEPTED.value: (
        "Order {order_number}\n\n"
        "Your order has been accepted by the restaurant.\n\n"
        "We\'ll start preparing it shortly."
    ),
    OrderStatus.PREPARING.value: (
        "Order {order_number}\n\n"
        "Your order is now being prepared."
    ),
    OrderStatus.READY.value: (
        "Order {order_number}\n\n"
        "Your order is ready.\n\n"
        "Please collect it from your table/service area."
    ),
    OrderStatus.SERVED.value: (
        "Order {order_number}\n\n"
        "Your order has been served.\n\n"
        "Thank you for dining with us!"
    ),
    OrderStatus.CANCELLED.value: (
        "Order {order_number}\n\n"
        "Your order has been cancelled.\n\n"
        "Please contact restaurant staff if you need assistance."
    ),
}


def sanitize_message_error(err_str: str) -> str:
    """
    Remove phone numbers and credentials from error messages before logging or persisting.
    """
    # Mask telephone numbers (8 to 15 digits, optionally with leading +)
    sanitized = re.sub(r"\+?\b\d{8,15}\b", "[MASKED_PHONE]", err_str)
    # Mask any Bearer tokens or secret keys
    sanitized = re.sub(r"Bearer\s+[A-Za-z0-9_\-\.]+", "Bearer [MASKED_TOKEN]", sanitized)
    return sanitized


class OrderNotificationService(BaseService):
    """
    Service managing real-time outbound customer WhatsApp status notifications
    for kitchen lifecycle events.
    """
    def __init__(
        self,
        session: AsyncSession,
        client: Optional[BaseWhatsAppClient] = None,
        whatsapp_client: Optional[BaseWhatsAppClient] = None,
    ) -> None:
        super().__init__(session)
        self.client = client or whatsapp_client or default_whatsapp_client
        self.notification_repo = OrderNotificationRepository(session)

    async def _get_order_with_session_and_customer(self, order_id: UUID) -> Optional[Order]:
        """
        Fetch order eagerly loading session and customer relationships.
        """
        stmt = (
            select(Order)
            .options(
                selectinload(Order.session).selectinload(CustomerSession.customer)
            )
            .where(Order.id == order_id)
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def send_kitchen_status_notification(
        self,
        restaurant_id: UUID,
        order_id: UUID,
        new_status: str,
    ) -> Optional[OrderNotification]:
        """
        Evaluate and dispatch an outbound WhatsApp notification to the customer
        for a kitchen order status update.

        Rules:
        - Only statuses in {ACCEPTED, PREPARING, READY, SERVED, CANCELLED} trigger notifications.
        - NEW and invalid statuses do not trigger customer notifications.
        - Multi-tenant validation ensures no cross-restaurant notification leak.
        - Closed sessions are handled safely (no notification sent).
        - Idempotency ensures the same (order_id, status, notification_type) is never dispatched twice.
        - Delivery failures are recorded with sanitized errors and NEVER raise exceptions to caller.
        """
        clean_status = new_status.upper().strip()

        # 1. Check if this status warrants an outbound customer notification
        template = STATUS_NOTIFICATION_TEMPLATES.get(clean_status)
        if not template:
            logger.info(
                f"Status '{clean_status}' does not require customer notification for order '{order_id}'."
            )
            return None

        # 2. Retrieve order with session and customer
        order = await self._get_order_with_session_and_customer(order_id)
        if not order:
            logger.warning(f"Cannot notify: Order '{order_id}' not found.")
            return None

        # 3. Multi-tenant security check
        if order.restaurant_id != restaurant_id:
            logger.error(
                f"Tenant isolation mismatch: Order '{order_id}' belongs to restaurant "
                f"'{order.restaurant_id}', not '{restaurant_id}'."
            )
            return None

        customer_session = order.session
        if not customer_session:
            logger.warning(
                f"Cannot notify: Order '{order.order_number}' has no associated customer session."
            )
            return None

        if customer_session.restaurant_id != order.restaurant_id:
            logger.error(
                f"Tenant isolation violation: Session '{customer_session.id}' restaurant "
                f"'{customer_session.restaurant_id}' differs from order restaurant '{order.restaurant_id}'."
            )
            return None

        # 4. Closed session safety check
        if customer_session.status == "CLOSED":
            logger.warning(
                f"Skipping notification for order '{order.order_number}': session '{customer_session.id}' is CLOSED."
            )
            return None

        # 5. Resolve customer WhatsApp identity
        customer = customer_session.customer
        if not customer or not customer.whatsapp_customer_id:
            logger.warning(
                f"Cannot notify: Customer for session '{customer_session.id}' has no WhatsApp identifier."
            )
            return None

        whatsapp_phone = customer.whatsapp_customer_id
        recipient_masked = mask_identifier(whatsapp_phone)

        # 6. Idempotency check: Look for existing notification record
        existing = await self.notification_repo.get_by_order_status_type(
            order_id=order.id,
            status=clean_status,
            notification_type="STATUS_UPDATE",
        )

        if existing and existing.delivery_status == "SENT":
            logger.info(
                f"Notification for order '{order.order_number}' status '{clean_status}' already sent to {recipient_masked}. Skipping duplicate."
            )
            return existing

        # 7. Create or update notification record in PENDING state
        notification = existing
        if not notification:
            notification = OrderNotification(
                order_id=order.id,
                status=clean_status,
                notification_type="STATUS_UPDATE",
                recipient_reference=recipient_masked,
                delivery_status="PENDING",
            )
            self.session.add(notification)
            await self.session.flush()

        # 8. Dispatch notification via WhatsApp client with strict failure isolation
        formatted_message = template.format(order_number=order.order_number)
        try:
            record = await self.client.send_text(
                to=whatsapp_phone,
                text=formatted_message,
            )
            if record and not record.success:
                raise Exception(record.error or "WhatsApp delivery failed")
            notification.delivery_status = "SENT"
            notification.sent_at = datetime.now(timezone.utc)
            notification.error_message = None
            await self.session.commit()
            logger.info(
                f"Dispatched kitchen status '{clean_status}' notification for order '{order.order_number}' to {recipient_masked}."
            )
        except Exception as exc:
            err_sanitized = sanitize_message_error(str(exc))
            logger.error(
                f"WhatsApp delivery failed for order '{order.order_number}' status '{clean_status}' to {recipient_masked}: {err_sanitized}"
            )
            notification.delivery_status = "FAILED"
            notification.error_message = err_sanitized
            try:
                await self.session.commit()
            except Exception as db_err:
                logger.error(f"Failed to record notification failure in DB: {db_err}")

        return notification
