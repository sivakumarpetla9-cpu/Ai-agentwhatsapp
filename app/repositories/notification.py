from typing import List, Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order_notification import OrderNotification
from app.repositories.base import BaseRepository


class OrderNotificationRepository(BaseRepository[OrderNotification]):
    """
    Repository for managing persistent OrderNotification records.
    """
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(OrderNotification, session)

    async def get_by_order_status_type(
        self,
        order_id: UUID,
        status: str,
        notification_type: str = "STATUS_UPDATE",
    ) -> Optional[OrderNotification]:
        """
        Fetch notification record for an order and status to check idempotency.
        """
        stmt = (
            select(OrderNotification)
            .where(
                OrderNotification.order_id == order_id,
                OrderNotification.status == status,
                OrderNotification.notification_type == notification_type,
            )
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_notifications_for_order(
        self, order_id: UUID
    ) -> List[OrderNotification]:
        """
        List all notifications attempted for an order.
        """
        stmt = (
            select(OrderNotification)
            .where(OrderNotification.order_id == order_id)
            .order_by(OrderNotification.created_at.asc())
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
