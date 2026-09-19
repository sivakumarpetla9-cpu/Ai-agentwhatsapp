from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError
from app.database.session import get_db
from app.schemas.customer_menu import CustomerFullMenuResponse
from app.schemas.menu import MenuCategoryResponse, MenuItemResponse
from app.services.customer_menu import CustomerMenuService

router = APIRouter()


def get_customer_menu_service(session: AsyncSession = Depends(get_db)) -> CustomerMenuService:
    return CustomerMenuService(session)


def resolve_session_id(
    x_session_id: Optional[UUID] = Header(None, alias="X-Session-ID", description="Customer session ID via HTTP header"),
    session_id: Optional[UUID] = Query(None, description="Customer session ID via query parameter"),
) -> UUID:
    """
    Resolve active session ID from either X-Session-ID header or session_id query parameter.
    """
    resolved = x_session_id or session_id
    if not resolved:
        raise BadRequestError(
            message="Session context required. Provide via 'X-Session-ID' header or 'session_id' parameter.",
            error_code="SESSION_REQUIRED",
        )
    return resolved


@router.get(
    "",
    response_model=CustomerFullMenuResponse,
    status_code=status.HTTP_200_OK,
    summary="Get customer menu",
    description="Returns complete dining menu with active categories and available items for the customer's active session.",
)
async def get_menu(
    session_id: UUID = Depends(resolve_session_id),
    service: CustomerMenuService = Depends(get_customer_menu_service),
) -> CustomerFullMenuResponse:
    return await service.get_full_menu(session_id)


@router.get(
    "/categories",
    response_model=List[MenuCategoryResponse],
    status_code=status.HTTP_200_OK,
    summary="Get menu categories",
    description="Returns active categories in display order for the customer's active session.",
)
async def get_categories(
    session_id: UUID = Depends(resolve_session_id),
    service: CustomerMenuService = Depends(get_customer_menu_service),
) -> List[MenuCategoryResponse]:
    return await service.get_categories(session_id)


@router.get(
    "/categories/{category_id}/items",
    response_model=List[MenuItemResponse],
    status_code=status.HTTP_200_OK,
    summary="Get items in category",
    description="Returns available items in the specified category for the customer's active session.",
)
async def get_category_items(
    category_id: UUID,
    session_id: UUID = Depends(resolve_session_id),
    service: CustomerMenuService = Depends(get_customer_menu_service),
) -> List[MenuItemResponse]:
    return await service.get_category_items(session_id, category_id)
