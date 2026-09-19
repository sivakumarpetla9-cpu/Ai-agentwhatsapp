from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.schemas.menu import MenuCategoryResponse, MenuItemResponse
from app.schemas.restaurant import RestaurantResponse, RestaurantTableResponse
from app.services.restaurant import RestaurantService

router = APIRouter()


def get_restaurant_service(session: AsyncSession = Depends(get_db)) -> RestaurantService:
    """
    Dependency injection provider for RestaurantService.
    """
    return RestaurantService(session)


@router.get(
    "",
    response_model=List[RestaurantResponse],
    status_code=status.HTTP_200_OK,
    summary="List restaurants",
    description="Retrieve all active restaurants with pagination.",
)
async def list_restaurants(
    skip: int = Query(0, ge=0, description="Offset count for pagination"),
    limit: int = Query(100, ge=1, le=100, description="Limit count for pagination"),
    service: RestaurantService = Depends(get_restaurant_service),
) -> List[RestaurantResponse]:
    return await service.list_restaurants(skip=skip, limit=limit)


@router.get(
    "/{restaurant_id}",
    response_model=RestaurantResponse,
    status_code=status.HTTP_200_OK,
    summary="Get restaurant details",
    description="Retrieve public profile for a specific restaurant.",
)
async def get_restaurant(
    restaurant_id: UUID,
    service: RestaurantService = Depends(get_restaurant_service),
) -> RestaurantResponse:
    return await service.get_restaurant(restaurant_id)


@router.get(
    "/{restaurant_id}/tables",
    response_model=List[RestaurantTableResponse],
    status_code=status.HTTP_200_OK,
    summary="List restaurant tables",
    description="Retrieve all tables belonging to a specific restaurant.",
)
async def list_tables(
    restaurant_id: UUID,
    service: RestaurantService = Depends(get_restaurant_service),
) -> List[RestaurantTableResponse]:
    return await service.list_tables(restaurant_id)


@router.get(
    "/{restaurant_id}/menu/categories",
    response_model=List[MenuCategoryResponse],
    status_code=status.HTTP_200_OK,
    summary="List restaurant menu categories",
    description="Retrieve ordered list of active menu categories for a restaurant.",
)
async def list_menu_categories(
    restaurant_id: UUID,
    service: RestaurantService = Depends(get_restaurant_service),
) -> List[MenuCategoryResponse]:
    return await service.list_categories(restaurant_id)


@router.get(
    "/{restaurant_id}/menu/items",
    response_model=List[MenuItemResponse],
    status_code=status.HTTP_200_OK,
    summary="List restaurant menu items",
    description="Retrieve available menu items for a restaurant, optionally filtered by category.",
)
async def list_menu_items(
    restaurant_id: UUID,
    category_id: Optional[UUID] = Query(None, description="Optional category filter"),
    service: RestaurantService = Depends(get_restaurant_service),
) -> List[MenuItemResponse]:
    return await service.list_menu_items(restaurant_id, category_id=category_id)
