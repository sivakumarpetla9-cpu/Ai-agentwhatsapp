from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError
from app.database.session import get_db
from app.schemas.cart import (
    AddToCartRequest,
    CartResponse,
    UpdateCartItemRequest,
)
from app.services.cart import CartService

router = APIRouter()


def get_cart_service(session: AsyncSession = Depends(get_db)) -> CartService:
    return CartService(session)


def resolve_cart_session_id(
    x_session_id: Optional[UUID] = Header(None, alias="X-Session-ID", description="Customer session ID via HTTP header"),
    session_id: Optional[UUID] = Query(None, description="Customer session ID via query parameter"),
) -> UUID:
    resolved = x_session_id or session_id
    if not resolved:
        raise BadRequestError(
            message="Session context required. Provide via 'X-Session-ID' header or 'session_id' parameter.",
            error_code="SESSION_REQUIRED",
        )
    return resolved


@router.get(
    "",
    response_model=CartResponse,
    status_code=status.HTTP_200_OK,
    summary="Get active cart",
    description="Retrieve the customer's current active shopping cart with calculated line totals and subtotal.",
)
async def get_cart(
    session_id: UUID = Depends(resolve_cart_session_id),
    service: CartService = Depends(get_cart_service),
) -> CartResponse:
    return await service.get_cart(session_id)


@router.post(
    "/items",
    response_model=CartResponse,
    status_code=status.HTTP_200_OK,
    summary="Add item to cart",
    description="Add an available menu item to the cart. If already present, increments quantity.",
)
async def add_cart_item(
    payload: AddToCartRequest,
    x_session_id: Optional[UUID] = Header(None, alias="X-Session-ID"),
    service: CartService = Depends(get_cart_service),
) -> CartResponse:
    session_id = payload.session_id or x_session_id
    if not session_id:
        raise BadRequestError(
            message="Session context required. Provide 'session_id' in request body or 'X-Session-ID' header.",
            error_code="SESSION_REQUIRED",
        )
    return await service.add_item(
        session_id=session_id,
        menu_item_id=payload.menu_item_id,
        quantity=payload.quantity,
    )


@router.patch(
    "/items/{cart_item_id}",
    response_model=CartResponse,
    status_code=status.HTTP_200_OK,
    summary="Update cart item quantity",
    description="Update quantity for an existing cart item (must be > 0).",
)
async def update_cart_item(
    cart_item_id: UUID,
    payload: UpdateCartItemRequest,
    session_id: UUID = Depends(resolve_cart_session_id),
    service: CartService = Depends(get_cart_service),
) -> CartResponse:
    return await service.update_item_quantity(
        session_id=session_id,
        cart_item_id=cart_item_id,
        quantity=payload.quantity,
    )


@router.delete(
    "/items/{cart_item_id}",
    response_model=CartResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove cart item",
    description="Remove a line item from the active cart.",
)
async def remove_cart_item(
    cart_item_id: UUID,
    session_id: UUID = Depends(resolve_cart_session_id),
    service: CartService = Depends(get_cart_service),
) -> CartResponse:
    return await service.remove_item(session_id=session_id, cart_item_id=cart_item_id)


@router.post(
    "/clear",
    response_model=CartResponse,
    status_code=status.HTTP_200_OK,
    summary="Clear cart",
    description="Remove all items from the active cart while retaining the Cart record.",
)
async def clear_cart(
    session_id: UUID = Depends(resolve_cart_session_id),
    service: CartService = Depends(get_cart_service),
) -> CartResponse:
    return await service.clear_cart(session_id=session_id)
