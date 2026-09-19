import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import Customer, CustomerSession
from app.models.restaurant import Restaurant, RestaurantTable, generate_qr_token
from app.services.session import mask_identifier


@pytest.fixture
async def setup_session_test_data(db_session: AsyncSession):
    """
    Creates two restaurants with active and inactive tables for session testing.
    """
    # Active Restaurant A
    restaurant_a = Restaurant(
        name="SpiceBox Active",
        phone_number="+919876543210",
        is_active=True,
    )
    # Inactive Restaurant B
    restaurant_b = Restaurant(
        name="Closed Diner",
        phone_number="+919876543211",
        is_active=False,
    )
    db_session.add_all([restaurant_a, restaurant_b])
    await db_session.flush()

    # Restaurant A Tables
    table_a1_active = RestaurantTable(
        restaurant_id=restaurant_a.id,
        table_number="Table 1",
        qr_token="qr-token-a1-valid",
        is_active=True,
    )
    table_a2_inactive = RestaurantTable(
        restaurant_id=restaurant_a.id,
        table_number="Table 2",
        qr_token="qr-token-a2-inactive",
        is_active=False,
    )

    # Restaurant B Tables (in inactive restaurant)
    table_b1 = RestaurantTable(
        restaurant_id=restaurant_b.id,
        table_number="Table B1",
        qr_token="qr-token-b1-inactive-res",
        is_active=True,
    )

    db_session.add_all([table_a1_active, table_a2_inactive, table_b1])
    await db_session.commit()

    return {
        "restaurant_a": restaurant_a,
        "restaurant_b": restaurant_b,
        "table_a1": table_a1_active,
        "table_a2": table_a2_inactive,
        "table_b1": table_b1,
    }


@pytest.mark.asyncio
async def test_1_valid_qr_token_resolves_correct_restaurant_and_table(
    async_client: AsyncClient, setup_session_test_data: dict
) -> None:
    """1. Test that a valid QR token resolves the correct restaurant and table."""
    data = setup_session_test_data
    token = data["table_a1"].qr_token

    response = await async_client.get(f"/api/v1/entry/qr/{token}")
    assert response.status_code == 200
    res_body = response.json()

    assert res_body["restaurant"]["id"] == str(data["restaurant_a"].id)
    assert res_body["restaurant"]["name"] == "SpiceBox Active"
    assert res_body["table"]["id"] == str(data["table_a1"].id)
    assert res_body["table"]["table_number"] == "Table 1"
    # Ensure QR token is NOT exposed in the response
    assert "qr_token" not in str(res_body)


@pytest.mark.asyncio
async def test_2_invalid_qr_token_returns_error(async_client: AsyncClient) -> None:
    """2. Test that an invalid QR token returns an appropriate 404 error."""
    response = await async_client.get("/api/v1/entry/qr/non-existent-token-xyz")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "QR_TOKEN_NOT_FOUND"


@pytest.mark.asyncio
async def test_3_inactive_restaurant_qr_cannot_create_session(
    async_client: AsyncClient, setup_session_test_data: dict
) -> None:
    """3. Test that inactive restaurant QR cannot create a valid session."""
    data = setup_session_test_data
    token = data["table_b1"].qr_token

    # Direct QR resolution check
    res_resolve = await async_client.get(f"/api/v1/entry/qr/{token}")
    assert res_resolve.status_code == 400
    assert res_resolve.json()["error"]["code"] == "RESTAURANT_INACTIVE"

    # Session creation attempt
    payload = {
        "customer_session_identity": "+919999900001",
        "qr_token": token,
    }
    res_session = await async_client.post("/api/v1/sessions/from-qr", json=payload)
    assert res_session.status_code == 400
    assert res_session.json()["error"]["code"] == "RESTAURANT_INACTIVE"


@pytest.mark.asyncio
async def test_4_inactive_table_qr_cannot_create_session(
    async_client: AsyncClient, setup_session_test_data: dict
) -> None:
    """4. Test that inactive table QR cannot create a valid session."""
    data = setup_session_test_data
    token = data["table_a2"].qr_token

    # Direct QR resolution check
    res_resolve = await async_client.get(f"/api/v1/entry/qr/{token}")
    assert res_resolve.status_code == 400
    assert res_resolve.json()["error"]["code"] == "TABLE_INACTIVE"

    # Session creation attempt
    payload = {
        "customer_session_identity": "+919999900001",
        "qr_token": token,
    }
    res_session = await async_client.post("/api/v1/sessions/from-qr", json=payload)
    assert res_session.status_code == 400
    assert res_session.json()["error"]["code"] == "TABLE_INACTIVE"


@pytest.mark.asyncio
async def test_5_direct_table_listing_only_returns_active_tables(
    async_client: AsyncClient, setup_session_test_data: dict
) -> None:
    """5. Test that direct table listing only returns active tables."""
    data = setup_session_test_data
    res_id = data["restaurant_a"].id

    response = await async_client.get(f"/api/v1/entry/restaurants/{res_id}/tables")
    assert response.status_code == 200
    tables = response.json()["tables"]

    # Table 1 is active, Table 2 is inactive
    table_numbers = [t["table_number"] for t in tables]
    assert "Table 1" in table_numbers
    assert "Table 2" not in table_numbers
    # Verify QR token is NOT exposed in the table selection list
    for t in tables:
        assert "qr_token" not in t


@pytest.mark.asyncio
async def test_6_table_from_another_restaurant_cannot_be_selected(
    async_client: AsyncClient, setup_session_test_data: dict
) -> None:
    """6. Test that a table from another restaurant cannot be selected."""
    data = setup_session_test_data
    res_a_id = data["restaurant_a"].id
    table_b1_id = data["table_b1"].id

    payload = {
        "customer_session_identity": "+919999900002",
        "restaurant_id": str(res_a_id),
        "table_id": str(table_b1_id),  # Belongs to Restaurant B!
    }
    response = await async_client.post("/api/v1/sessions", json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CROSS_RESTAURANT_TABLE_REJECTED"


@pytest.mark.asyncio
async def test_7_valid_direct_table_selection_creates_active_session(
    async_client: AsyncClient, setup_session_test_data: dict
) -> None:
    """7. Test that valid direct table selection creates an active session."""
    data = setup_session_test_data
    payload = {
        "customer_session_identity": "+919876500001",
        "restaurant_id": str(data["restaurant_a"].id),
        "table_id": str(data["table_a1"].id),
    }
    response = await async_client.post("/api/v1/sessions", json=payload)
    assert response.status_code == 200
    session_data = response.json()

    assert "session_id" in session_data
    assert session_data["restaurant_id"] == str(data["restaurant_a"].id)
    assert session_data["table_id"] == str(data["table_a1"].id)
    assert session_data["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_8_qr_session_creation_works(
    async_client: AsyncClient, setup_session_test_data: dict
) -> None:
    """8. Test that QR session creation works."""
    data = setup_session_test_data
    payload = {
        "customer_session_identity": "+919876500002",
        "qr_token": data["table_a1"].qr_token,
    }
    response = await async_client.post("/api/v1/sessions/from-qr", json=payload)
    assert response.status_code == 200
    session_data = response.json()

    assert "session_id" in session_data
    assert session_data["restaurant_id"] == str(data["restaurant_a"].id)
    assert session_data["table_id"] == str(data["table_a1"].id)
    assert session_data["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_9_active_session_can_be_reused(
    async_client: AsyncClient, setup_session_test_data: dict
) -> None:
    """9. Test that an active session is reused for the same table & customer."""
    data = setup_session_test_data
    payload = {
        "customer_session_identity": "+919876500003",
        "restaurant_id": str(data["restaurant_a"].id),
        "table_id": str(data["table_a1"].id),
    }
    res1 = await async_client.post("/api/v1/sessions", json=payload)
    session_id_1 = res1.json()["session_id"]

    # Call again with the same credentials
    res2 = await async_client.post("/api/v1/sessions", json=payload)
    session_id_2 = res2.json()["session_id"]

    assert session_id_1 == session_id_2


@pytest.mark.asyncio
async def test_10_expired_session_cannot_be_treated_as_active(
    db_session: AsyncSession, setup_session_test_data: dict
) -> None:
    """10. Test that an expired session is not treated as active."""
    data = setup_session_test_data
    customer = Customer(whatsapp_customer_id="+919876500004")
    db_session.add(customer)
    await db_session.flush()

    # Create an expired session in the past
    expired_session = CustomerSession(
        customer_id=customer.id,
        restaurant_id=data["restaurant_a"].id,
        table_id=data["table_a1"].id,
        status="ACTIVE",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    db_session.add(expired_session)
    await db_session.commit()

    assert expired_session.is_currently_active is False


@pytest.mark.asyncio
async def test_11_customer_whatsapp_identifier_never_in_public_response(
    async_client: AsyncClient, setup_session_test_data: dict
) -> None:
    """11. Test that customer WhatsApp identifier is never exposed in response bodies."""
    data = setup_session_test_data
    raw_phone = "+919876500005"
    payload = {
        "customer_session_identity": raw_phone,
        "restaurant_id": str(data["restaurant_a"].id),
        "table_id": str(data["table_a1"].id),
    }
    response = await async_client.post("/api/v1/sessions", json=payload)
    assert response.status_code == 200
    assert raw_phone not in response.text


def test_12_mask_identifier_utility() -> None:
    """12. Test that identity masking prevents logging raw customer WhatsApp IDs."""
    raw = "+919876543210"
    masked = mask_identifier(raw)
    assert raw not in masked
    assert masked == "+9******10"

    short = "123"
    assert mask_identifier(short) == "****"


@pytest.mark.asyncio
async def test_13_cross_restaurant_session_rejected_at_db_constraint(
    db_session: AsyncSession, setup_session_test_data: dict
) -> None:
    """13. Test that cross-restaurant session assignment violates composite foreign key constraint."""
    data = setup_session_test_data
    customer = Customer(whatsapp_customer_id="+919876500006")
    db_session.add(customer)
    await db_session.flush()

    # Illegal attempt: table_b1 belongs to restaurant_b, but session points to restaurant_a
    illegal_session = CustomerSession(
        customer_id=customer.id,
        restaurant_id=data["restaurant_a"].id,
        table_id=data["table_b1"].id,
        status="ACTIVE",
    )
    db_session.add(illegal_session)
    with pytest.raises(IntegrityError):
        await db_session.flush()
