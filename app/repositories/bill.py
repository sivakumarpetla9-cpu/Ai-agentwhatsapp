from typing import List, Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bill import Bill, BillItem, BillStatus
from app.repositories.base import BaseRepository


class BillRepository(BaseRepository[Bill]):
    """
    Repository for consolidated Bill domain entities.
    """
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Bill, session)

    async def get_by_id(self, bill_id: UUID) -> Optional[Bill]:
        """
        Retrieve bill by primary key with fresh in-memory population.
        """
        stmt = (
            select(Bill)
            .where(Bill.id == bill_id)
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_id_and_restaurant(
        self, bill_id: UUID, restaurant_id: UUID
    ) -> Optional[Bill]:
        """
        Retrieve bill verifying tenant restaurant ownership.
        """
        stmt = (
            select(Bill)
            .where(Bill.id == bill_id, Bill.restaurant_id == restaurant_id)
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_id_and_session(
        self, bill_id: UUID, session_id: UUID
    ) -> Optional[Bill]:
        """
        Retrieve bill verifying customer session ownership.
        """
        stmt = (
            select(Bill)
            .where(Bill.id == bill_id, Bill.session_id == session_id)
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_open_bill_by_session(self, session_id: UUID) -> Optional[Bill]:
        """
        Retrieve active OPEN bill for a dining session, if one exists.
        """
        stmt = (
            select(Bill)
            .where(
                Bill.session_id == session_id,
                Bill.status == BillStatus.OPEN.value,
            )
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_latest_bill_by_session(self, session_id: UUID) -> Optional[Bill]:
        """
        Retrieve most recent bill for a session (OPEN or SETTLED).
        """
        stmt = (
            select(Bill)
            .where(Bill.session_id == session_id)
            .order_by(Bill.created_at.desc())
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_bills_by_session(self, session_id: UUID) -> List[Bill]:
        """
        List all bills belonging to a customer session, newest first.
        """
        stmt = (
            select(Bill)
            .where(Bill.session_id == session_id)
            .order_by(Bill.created_at.desc())
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class BillItemRepository(BaseRepository[BillItem]):
    """
    Repository for individual BillItem records.
    """
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(BillItem, session)

    async def get_by_bill_and_order_item(
        self, bill_id: UUID, order_item_id: UUID
    ) -> Optional[BillItem]:
        """
        Retrieve existing bill item for a specific order item.
        """
        stmt = (
            select(BillItem)
            .where(BillItem.bill_id == bill_id, BillItem.order_item_id == order_item_id)
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
