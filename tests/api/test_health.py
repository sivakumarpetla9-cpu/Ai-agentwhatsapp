import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check_returns_200_and_status_ok(async_client: AsyncClient) -> None:
    """
    Test GET /api/v1/health returns HTTP 200 and {"status": "ok"}.
    """
    response = await async_client.get("/api/v1/health")

    assert response.status_code == 200
    data = response.json()
    assert data == {"status": "ok"}
