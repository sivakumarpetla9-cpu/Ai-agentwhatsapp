from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.schemas.health import HealthResponse

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Health check",
    description="Returns the operational status of the service.",
    response_description="Service is healthy and ready to receive requests.",
)
async def get_health() -> HealthResponse:
    """
    Health check endpoint returning operational status.
    """
    return HealthResponse(status="ok")


@router.get(
    "/health/live",
    status_code=status.HTTP_200_OK,
    summary="Liveness check",
    description="Kubernetes/container liveness probe confirming process is responsive.",
)
async def get_live() -> dict:
    """
    Liveness probe returning 200 OK when application process is running.
    """
    return {"status": "live"}


@router.get(
    "/health/ready",
    status_code=status.HTTP_200_OK,
    summary="Readiness check",
    description="Readiness probe confirming database connectivity before routing traffic.",
)
async def get_ready(
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Readiness probe validating database connectivity.
    """
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "ready", "database": "connected"}
    except Exception as e:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unhealthy", "database": "disconnected", "error": str(e)}

