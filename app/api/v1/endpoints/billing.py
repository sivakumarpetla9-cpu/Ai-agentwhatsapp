import logging
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.schemas.billing import (
    BillResponse,
    GenerateBillRequest,
    SettleBillRequest,
)
from app.services.billing import BillingService

logger = logging.getLogger("whatsapp_ordering.api.billing")

router = APIRouter()


@router.get(
    "",
    response_model=BillResponse,
    status_code=status.HTTP_200_OK,
    summary="Get session bill",
    description="Retrieve the current consolidated bill for an active customer dining session.",
)
async def get_session_bill(
    session_id: UUID = Query(..., description="Active dining session identifier"),
    db: AsyncSession = Depends(get_db),
) -> BillResponse:
    """
    Retrieve current bill for a dining session.
    """
    billing_service = BillingService(db)
    return await billing_service.get_bill_by_session(session_id)


@router.post(
    "/generate",
    response_model=BillResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate or retrieve open bill",
    description=(
        "Idempotently generate or retrieve the active OPEN bill consolidating all SERVED orders "
        "for the dining session. Safe for repeated requests."
    ),
)
async def generate_bill(
    payload: GenerateBillRequest,
    db: AsyncSession = Depends(get_db),
) -> BillResponse:
    """
    Create or fetch open consolidated bill.
    """
    billing_service = BillingService(db)
    bill = await billing_service.generate_or_get_bill(payload.session_id)
    await db.commit()
    return bill


@router.post(
    "/{bill_id}/settle",
    response_model=BillResponse,
    status_code=status.HTTP_200_OK,
    summary="Settle bill and close table session",
    description=(
        "Finalize table session settlement. Validates that no unresolved orders remain, "
        "marks bill SETTLED, closes the customer session, and frees the table for new diners."
    ),
)
async def settle_bill(
    bill_id: UUID,
    payload: Optional[SettleBillRequest] = None,
    db: AsyncSession = Depends(get_db),
) -> BillResponse:
    """
    Finalize bill settlement and close table dining session.
    """
    restaurant_id = payload.restaurant_id if payload else None
    session_id = payload.session_id if payload else None

    billing_service = BillingService(db)
    bill = await billing_service.settle_bill(
        bill_id=bill_id,
        restaurant_id=restaurant_id,
        session_id=session_id,
    )
    await db.commit()
    return bill
