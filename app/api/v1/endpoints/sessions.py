from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.schemas.session import (
    CreateQRSessionRequest,
    CreateSessionRequest,
    CustomerSessionResponse,
)
from app.services.session import SessionService

router = APIRouter()


def get_session_service(session: AsyncSession = Depends(get_db)) -> SessionService:
    """
    Dependency injection provider for SessionService.
    """
    return SessionService(session)


@router.post(
    "",
    response_model=CustomerSessionResponse,
    status_code=status.HTTP_200_OK,
    summary="Create or resume session via direct selection",
    description="Creates a dining session after the customer selects an active table in direct WhatsApp flow.",
)
async def create_direct_session(
    payload: CreateSessionRequest,
    service: SessionService = Depends(get_session_service),
) -> CustomerSessionResponse:
    """
    Create or resume an active dining session for direct WhatsApp flow.
    """
    return await service.create_or_resume_direct_session(
        customer_session_identity=payload.customer_session_identity,
        restaurant_id=payload.restaurant_id,
        table_id=payload.table_id,
    )


@router.post(
    "/from-qr",
    response_model=CustomerSessionResponse,
    status_code=status.HTTP_200_OK,
    summary="Create or resume session via QR token",
    description="Validates QR token and creates or resumes a dining session directly from scanned QR.",
)
async def create_session_from_qr(
    payload: CreateQRSessionRequest,
    service: SessionService = Depends(get_session_service),
) -> CustomerSessionResponse:
    """
    Create or resume an active dining session from scanned table QR token.
    """
    return await service.create_or_resume_qr_session(
        customer_session_identity=payload.customer_session_identity,
        qr_token=payload.qr_token,
    )
