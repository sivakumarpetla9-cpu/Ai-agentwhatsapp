from typing import List, Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.restaurant import Restaurant, RestaurantTable
from app.repositories.base import BaseRepository, BaseRestaurantRepository


class RestaurantRepository(BaseRepository[Restaurant]):
    """
    Repository for Restaurant tenant operations.
    """
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Restaurant, session)

    async def list_active(self, skip: int = 0, limit: int = 100) -> List[Restaurant]:
        """
        List active restaurants with pagination.
        """
        stmt = (
            select(Restaurant)
            .where(Restaurant.is_active.is_(True))
            .order_by(Restaurant.name)
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class RestaurantTableRepository(BaseRestaurantRepository[RestaurantTable]):
    """
    Repository for RestaurantTable operations.
    """
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(RestaurantTable, session)

    async def get_by_qr_token(self, qr_token: str) -> Optional[RestaurantTable]:
        """
        Locate a table using its opaque high-entropy QR token.
        """
        stmt = select(RestaurantTable).where(RestaurantTable.qr_token == qr_token)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_table_number(
        self, restaurant_id: UUID, table_number: str
    ) -> Optional[RestaurantTable]:
        """
        Lookup a table by restaurant_id and human-readable table_number.
        """
        stmt = select(RestaurantTable).where(
            RestaurantTable.restaurant_id == restaurant_id,
            RestaurantTable.table_number == table_number,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_by_restaurant(
        self, restaurant_id: UUID, skip: int = 0, limit: int = 100
    ) -> List[RestaurantTable]:
        """
        List tables belonging to a specific restaurant ordered by table_number.
        """
        stmt = (
            select(RestaurantTable)
            .where(RestaurantTable.restaurant_id == restaurant_id)
            .order_by(RestaurantTable.table_number)
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
