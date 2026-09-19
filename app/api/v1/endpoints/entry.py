from uuid import UUID
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.schemas.session import DirectTablesResponse, QREntryResponse
from app.services.session import SessionService

router = APIRouter()


def get_session_service(session: AsyncSession = Depends(get_db)) -> SessionService:
    """
    Dependency injection provider for SessionService.
    """
    return SessionService(session)


@router.get(
    "/qr/{qr_token}",
    response_model=QREntryResponse,
    status_code=status.HTTP_200_OK,
    summary="Resolve table QR code",
    description="Resolves physical table QR token to public restaurant and table context. Does not repeat token.",
)
async def resolve_qr_entry(
    qr_token: str,
    service: SessionService = Depends(get_session_service),
) -> QREntryResponse:
    """
    Flow A Entry: Customer scans table QR code.
    Returns safe restaurant and table information without exposing secrets.
    """
    return await service.resolve_qr(qr_token)


@router.get(
    "/restaurants/{restaurant_id}/tables",
    response_model=DirectTablesResponse,
    status_code=status.HTTP_200_OK,
    summary="List active tables for direct selection",
    description="Returns available active tables for customer selection in direct WhatsApp conversation flow.",
)
async def list_direct_entry_tables(
    restaurant_id: UUID,
    service: SessionService = Depends(get_session_service),
) -> DirectTablesResponse:
    """
    Flow B Entry: Customer messages restaurant directly.
    Returns list of active tables available for dining.
    """
    return await service.list_active_tables_for_direct_entry(restaurant_id)
