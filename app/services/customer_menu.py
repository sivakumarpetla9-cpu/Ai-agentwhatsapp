from typing import List
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, EntityNotFoundError
from app.models.customer import CustomerSession
from app.repositories.customer import CustomerSessionRepository
from app.repositories.menu import MenuCategoryRepository, MenuItemRepository
from app.repositories.restaurant import RestaurantRepository
from app.schemas.customer_menu import (
    CustomerCategoryResponse,
    CustomerFullMenuResponse,
    CustomerMenuItemResponse,
)
from app.schemas.menu import MenuCategoryResponse, MenuItemResponse
from app.services.base import BaseService


class CustomerMenuService(BaseService):
    """
    Service for customer-facing menu browsing strictly scoped to the active session's restaurant.
    """
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.session_repo = CustomerSessionRepository(session)
        self.restaurant_repo = RestaurantRepository(session)
        self.category_repo = MenuCategoryRepository(session)
        self.menu_item_repo = MenuItemRepository(session)

    async def _validate_and_get_session(self, session_id: UUID) -> CustomerSession:
        """
        Validate that the customer session is active, unexpired, and its restaurant is active.
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

    async def get_full_menu(self, session_id: UUID) -> CustomerFullMenuResponse:
        """
        Retrieve complete restaurant menu containing only active categories and available items,
        strictly derived from the session context.
        """
        customer_session = await self._validate_and_get_session(session_id)
        restaurant_id = customer_session.restaurant_id

        # 1. Fetch active categories in display order
        categories = await self.category_repo.list_by_restaurant(
            restaurant_id=restaurant_id,
            active_only=True,
        )

        category_responses: List[CustomerCategoryResponse] = []
        for cat in categories:
            # 2. Fetch available items for this category
            items = await self.menu_item_repo.list_by_restaurant(
                restaurant_id=restaurant_id,
                category_id=cat.id,
                available_only=True,
            )
            item_responses = [
                CustomerMenuItemResponse.model_validate(item) for item in items
            ]
            category_responses.append(
                CustomerCategoryResponse(
                    id=cat.id,
                    name=cat.name,
                    description=cat.description,
                    display_order=cat.display_order,
                    items=item_responses,
                )
            )

        return CustomerFullMenuResponse(
            restaurant_id=restaurant_id,
            categories=category_responses,
        )

    async def get_categories(self, session_id: UUID) -> List[MenuCategoryResponse]:
        """
        Retrieve list of active categories for the customer's session restaurant.
        """
        customer_session = await self._validate_and_get_session(session_id)
        categories = await self.category_repo.list_by_restaurant(
            restaurant_id=customer_session.restaurant_id,
            active_only=True,
        )
        return [MenuCategoryResponse.model_validate(c) for c in categories]

    async def get_category_items(
        self, session_id: UUID, category_id: UUID
    ) -> List[MenuItemResponse]:
        """
        Retrieve available items in a specific category belonging to the session's restaurant.
        """
        customer_session = await self._validate_and_get_session(session_id)
        category = await self.category_repo.get_by_id(category_id)

        if not category or category.restaurant_id != customer_session.restaurant_id:
            raise EntityNotFoundError(
                message=f"Category '{category_id}' not found for this restaurant.",
                error_code="CATEGORY_NOT_FOUND",
            )

        if not category.is_active:
            raise BadRequestError(
                message="Category is currently inactive.",
                error_code="CATEGORY_INACTIVE",
            )

        items = await self.menu_item_repo.list_by_restaurant(
            restaurant_id=customer_session.restaurant_id,
            category_id=category_id,
            available_only=True,
        )
        return [MenuItemResponse.model_validate(i) for i in items]
