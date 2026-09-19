from typing import List, Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.orm import selectinload

from app.models.menu import MenuCategory, MenuItem
from app.repositories.base import BaseRestaurantRepository


class MenuCategoryRepository(BaseRestaurantRepository[MenuCategory]):
    """
    Repository for restaurant menu categories.
    """
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(MenuCategory, session)

    async def list_by_restaurant(
        self,
        restaurant_id: UUID,
        active_only: bool = True,
        skip: int = 0,
        limit: int = 100,
    ) -> List[MenuCategory]:
        """
        List categories for a restaurant ordered by display_order.
        """
        stmt = select(MenuCategory).where(MenuCategory.restaurant_id == restaurant_id)
        if active_only:
            stmt = stmt.where(MenuCategory.is_active.is_(True))
        stmt = stmt.order_by(MenuCategory.display_order, MenuCategory.name).offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class MenuItemRepository(BaseRestaurantRepository[MenuItem]):
    """
    Repository for restaurant menu items.
    """
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(MenuItem, session)

    async def get_by_id(self, id: UUID) -> Optional[MenuItem]:
        """
        Fetch a single menu item by ID eagerly loading its parent category.
        """
        stmt = (
            select(MenuItem)
            .where(MenuItem.id == id)
            .options(selectinload(MenuItem.category))
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_by_restaurant(
        self,
        restaurant_id: UUID,
        category_id: Optional[UUID] = None,
        available_only: bool = True,
        skip: int = 0,
        limit: int = 100,
    ) -> List[MenuItem]:
        """
        List menu items for a restaurant, optionally filtered by category.
        Ordered by display_order.
        """
        stmt = select(MenuItem).where(MenuItem.restaurant_id == restaurant_id)
        if category_id is not None:
            stmt = stmt.where(MenuItem.category_id == category_id)
        if available_only:
            stmt = stmt.where(MenuItem.is_available.is_(True))
        stmt = stmt.order_by(MenuItem.display_order, MenuItem.name).offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
