from typing import List, Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderItem
from app.repositories.base import BaseRepository


class OrderRepository(BaseRepository[Order]):
    """
    Repository for Order domain entities.
    """
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Order, session)

    async def get_by_id(self, order_id: UUID) -> Optional[Order]:
        """
        Fetch order by ID with fresh in-memory population.
        """
        stmt = (
            select(Order)
            .where(Order.id == order_id)
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_id_and_session(
        self, order_id: UUID, session_id: UUID
    ) -> Optional[Order]:
        """
        Fetch order verifying customer session ownership.
        """
        stmt = (
            select(Order)
            .where(Order.id == order_id, Order.customer_session_id == session_id)
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_id_and_restaurant(
        self, order_id: UUID, restaurant_id: UUID
    ) -> Optional[Order]:
        """
        Fetch order verifying restaurant ownership.
        """
        stmt = (
            select(Order)
            .where(Order.id == order_id, Order.restaurant_id == restaurant_id)
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_orders_by_session(self, session_id: UUID) -> List[Order]:
        """
        List all orders placed during a customer's dining session, newest first.
        """
        stmt = (
            select(Order)
            .where(Order.customer_session_id == session_id)
            .order_by(Order.created_at.desc())
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_orders_by_restaurant(
        self, restaurant_id: UUID, status: Optional[str] = None
    ) -> List[Order]:
        """
        List orders for a restaurant kitchen queue.
        Oldest orders first (FIFO for kitchen preparation).
        """
        stmt = select(Order).where(Order.restaurant_id == restaurant_id)
        if status:
            stmt = stmt.where(Order.status == status)
        stmt = stmt.order_by(Order.created_at.asc()).execution_options(populate_existing=True)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class OrderItemRepository(BaseRepository[OrderItem]):
    """
    Repository for individual OrderItem line items.
    """
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(OrderItem, session)
