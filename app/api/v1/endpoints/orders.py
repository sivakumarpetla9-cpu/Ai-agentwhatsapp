from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError
from app.database.session import get_db
from app.schemas.order import CheckoutRequest, OrderResponse
from app.services.order import OrderService

router = APIRouter()


def get_order_service(session: AsyncSession = Depends(get_db)) -> OrderService:
    return OrderService(session)


def resolve_session_id(
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


@router.post(
    "/checkout",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Place order from active cart",
    description="Check out the customer's active dining cart into a placed order with status NEW.",
)
async def checkout_cart(
    payload: CheckoutRequest,
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    return await service.checkout_cart(
        session_id=payload.session_id,
        special_instructions=payload.special_instructions,
    )


@router.get(
    "",
    response_model=List[OrderResponse],
    status_code=status.HTTP_200_OK,
    summary="List session orders",
    description="List all orders placed during the current active customer dining session.",
)
async def list_session_orders(
    session_id: UUID = Depends(resolve_session_id),
    service: OrderService = Depends(get_order_service),
) -> List[OrderResponse]:
    return await service.get_session_orders(session_id)


@router.get(
    "/{order_id}",
    response_model=OrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Get session order details",
    description="Retrieve live status and item details for a specific order belonging to the session.",
)
async def get_session_order(
    order_id: UUID,
    session_id: UUID = Depends(resolve_session_id),
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    return await service.get_order_for_session(session_id=session_id, order_id=order_id)
