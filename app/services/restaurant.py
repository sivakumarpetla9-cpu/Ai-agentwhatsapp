from typing import List, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EntityNotFoundError
from app.models.menu import MenuCategory, MenuItem
from app.models.restaurant import Restaurant, RestaurantTable
from app.repositories.menu import MenuCategoryRepository, MenuItemRepository
from app.repositories.restaurant import RestaurantRepository, RestaurantTableRepository
from app.services.base import BaseService


class RestaurantService(BaseService):
    """
    Business logic layer for Restaurant and Menu retrieval operations.
    """
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.restaurant_repo = RestaurantRepository(session)
        self.table_repo = RestaurantTableRepository(session)
        self.category_repo = MenuCategoryRepository(session)
        self.menu_item_repo = MenuItemRepository(session)

    async def list_restaurants(self, skip: int = 0, limit: int = 100) -> List[Restaurant]:
        """
        List all active restaurants.
        """
        return await self.restaurant_repo.list_active(skip=skip, limit=limit)

    async def get_restaurant(self, restaurant_id: UUID) -> Restaurant:
        """
        Get restaurant by ID or raise EntityNotFoundError.
        """
        restaurant = await self.restaurant_repo.get_by_id(restaurant_id)
        if not restaurant or not restaurant.is_active:
            raise EntityNotFoundError(
                message=f"Restaurant '{restaurant_id}' not found or inactive.",
                error_code="RESTAURANT_NOT_FOUND",
                details={"restaurant_id": str(restaurant_id)},
            )
        return restaurant

    async def list_tables(self, restaurant_id: UUID) -> List[RestaurantTable]:
        """
        List all tables for a given restaurant.
        """
        # Ensure restaurant exists
        await self.get_restaurant(restaurant_id)
        return await self.table_repo.list_by_restaurant(restaurant_id)

    async def list_categories(self, restaurant_id: UUID) -> List[MenuCategory]:
        """
        List menu categories for a given restaurant.
        """
        # Ensure restaurant exists
        await self.get_restaurant(restaurant_id)
        return await self.category_repo.list_by_restaurant(restaurant_id, active_only=True)

    async def list_menu_items(
        self, restaurant_id: UUID, category_id: Optional[UUID] = None
    ) -> List[MenuItem]:
        """
        List available menu items for a given restaurant, optionally filtered by category.
        """
        # Ensure restaurant exists
        await self.get_restaurant(restaurant_id)
        return await self.menu_item_repo.list_by_restaurant(
            restaurant_id=restaurant_id,
            category_id=category_id,
            available_only=True,
        )
