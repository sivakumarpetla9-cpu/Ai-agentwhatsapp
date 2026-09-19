import logging
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.schemas.order import KitchenOrderResponse, KitchenOrderStatusUpdateRequest
from app.services.order import OrderService
from app.services.order_notifications import OrderNotificationService

logger = logging.getLogger("whatsapp_ordering.api.kitchen")

router = APIRouter()


def get_order_service(session: AsyncSession = Depends(get_db)) -> OrderService:
    return OrderService(session)


def get_order_notification_service(
    session: AsyncSession = Depends(get_db),
) -> OrderNotificationService:
    return OrderNotificationService(session)


@router.get(
    "/orders",
    response_model=List[KitchenOrderResponse],
    status_code=status.HTTP_200_OK,
    summary="List kitchen orders",
    description="Retrieve kitchen queue for a restaurant, optionally filtered by status (e.g. NEW, ACCEPTED, PREPARING).",
)
async def list_kitchen_orders(
    restaurant_id: UUID = Query(..., description="Restaurant identifier"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
    service: OrderService = Depends(get_order_service),
) -> List[KitchenOrderResponse]:
    return await service.get_kitchen_orders(restaurant_id=restaurant_id, status=status_filter)


@router.patch(
    "/orders/{order_id}/status",
    response_model=KitchenOrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Update order status (Kitchen lifecycle)",
    description=(
        "Transition order along the lifecycle: "
        "NEW -> ACCEPTED -> PREPARING -> READY -> SERVED (or CANCELLED). "
        "Rejects invalid transitions."
    ),
)
async def update_order_status(
    order_id: UUID,
    payload: KitchenOrderStatusUpdateRequest,
    db: AsyncSession = Depends(get_db),
    service: OrderService = Depends(get_order_service),
    notification_service: OrderNotificationService = Depends(get_order_notification_service),
) -> KitchenOrderResponse:
    # 1. Advance state machine and persist order status transition
    order_response = await service.transition_order_status(
        restaurant_id=payload.restaurant_id,
        order_id=order_id,
        new_status=payload.status,
    )

    # 2. Explicitly commit the order status change before external side-effects
    await db.commit()

    # 3. Trigger WhatsApp status notification post-commit with failure isolation
    try:
        await notification_service.send_kitchen_status_notification(
            restaurant_id=payload.restaurant_id,
            order_id=order_id,
            new_status=payload.status,
        )
    except Exception as exc:
        logger.error(
            f"Failed to dispatch kitchen status notification for order '{order_id}': {exc}"
        )

    # 4. Return standard kitchen response (never exposes customer PII)
    return order_response
