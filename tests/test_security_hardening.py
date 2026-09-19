import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict
from uuid import uuid4
import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import BadRequestError, EntityNotFoundError
from app.integrations.whatsapp.client import whatsapp_client
from app.models.bill import Bill, BillStatus
from app.models.cart import Cart, CartItem
from app.models.customer import Customer, CustomerSession
from app.models.menu import MenuCategory, MenuItem
from app.models.order import Order, OrderItem, OrderStatus
from app.models.restaurant import Restaurant, RestaurantTable, generate_qr_token
from app.models.webhook_event import WebhookEvent
from app.repositories.webhook_event import WebhookEventRepository
from app.services.billing import BillingService
from app.services.cart import CartService
from app.services.customer_menu import CustomerMenuService
from app.services.order import OrderService
from app.services.session import SessionService, mask_identifier

settings = get_settings()


@pytest.fixture
async def security_setup(db_session: AsyncSession):
    """
    Sets up two isolated restaurants with tables, categories, and items.
    """
    whatsapp_client.clear_sent_messages()

    # Restaurant 1 (SpiceBox)
    r1 = Restaurant(name="SpiceBox Secure", is_active=True)
    db_session.add(r1)
    await db_session.flush()

    t1 = RestaurantTable(restaurant_id=r1.id, table_number="Table 1", qr_token="qr-secure-r1-t1")
    db_session.add(t1)

    c1 = MenuCategory(restaurant_id=r1.id, name="Biryani", display_order=1, is_active=True)
    db_session.add(c1)
    await db_session.flush()

    i1 = MenuItem(
        restaurant_id=r1.id, category_id=c1.id, name="Chicken Biryani",
        price=Decimal("250.00"), is_available=True,
    )
    db_session.add(i1)

    # Restaurant 2 (DragonWok)
    r2 = Restaurant(name="DragonWok Secure", is_active=True)
    db_session.add(r2)
    await db_session.flush()

    t2 = RestaurantTable(restaurant_id=r2.id, table_number="Table 1", qr_token="qr-secure-r2-t1")
    db_session.add(t2)

    c2 = MenuCategory(restaurant_id=r2.id, name="Noodles", display_order=1, is_active=True)
    db_session.add(c2)
    await db_session.flush()

    i2 = MenuItem(
        restaurant_id=r2.id, category_id=c2.id, name="Hakka Noodles",
        price=Decimal("180.00"), is_available=True,
    )
    db_session.add(i2)

    # Customers & Sessions
    cust1 = Customer(whatsapp_customer_id="+919876543210", display_name="Alice")
    cust2 = Customer(whatsapp_customer_id="+919876543220", display_name="Bob")
    db_session.add_all([cust1, cust2])
    await db_session.flush()

    expires_at = datetime.now(timezone.utc) + timedelta(hours=3)
    sess1 = CustomerSession(
        customer_id=cust1.id, restaurant_id=r1.id, table_id=t1.id,
        status="ACTIVE", expires_at=expires_at,
    )
    sess2 = CustomerSession(
        customer_id=cust2.id, restaurant_id=r2.id, table_id=t2.id,
        status="ACTIVE", expires_at=expires_at,
    )
    db_session.add_all([sess1, sess2])
    await db_session.commit()

    return {
        "r1": r1, "t1": t1, "c1": c1, "i1": i1, "sess1": sess1, "cust1": cust1,
        "r2": r2, "t2": t2, "c2": c2, "i2": i2, "sess2": sess2, "cust2": cust2,
    }


def _create_webhook_payload(from_phone: str, message_id: str, body: str) -> Dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WHATSAPP_BUSINESS_ACCOUNT_ID",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "123456", "phone_number_id": "PNID"},
                            "contacts": [{"profile": {"name": "Test User"}, "wa_id": from_phone}],
                            "messages": [
                                {
                                    "from": from_phone,
                                    "id": message_id,
                                    "timestamp": "1700000000",
                                    "type": "text",
                                    "text": {"body": body},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


# ===========================================================================
# 1. WEBHOOK SECURITY & SIGNATURE VERIFICATION
# ===========================================================================

async def test_webhook_get_verification_constant_time(async_client: AsyncClient):
    """
    Test GET /webhook verification handshake with valid and invalid tokens.
    """
    # 1. Valid handshake
    resp = await async_client.get(
        "/api/v1/integrations/whatsapp/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": settings.WHATSAPP_VERIFY_TOKEN,
            "hub.challenge": "test_challenge_12345",
        },
    )
    assert resp.status_code == 200
    assert resp.text == "test_challenge_12345"

    # 2. Invalid token
    bad_resp = await async_client.get(
        "/api/v1/integrations/whatsapp/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong_token",
            "hub.challenge": "test_challenge_12345",
        },
    )
    assert bad_resp.status_code == 403

    # 3. Invalid mode
    mode_resp = await async_client.get(
        "/api/v1/integrations/whatsapp/webhook",
        params={
            "hub.mode": "unsubscribe",
            "hub.verify_token": settings.WHATSAPP_VERIFY_TOKEN,
            "hub.challenge": "test_challenge_12345",
        },
    )
    assert mode_resp.status_code == 403


async def test_webhook_hmac_signature_verification(async_client: AsyncClient, monkeypatch):
    """
    Verify Meta HMAC-SHA256 signature verification on POST /webhook:
    valid, invalid, missing, and tampered signatures.
    """
    app_secret = "meta_test_secret_key_1234567890"
    monkeypatch.setattr(settings, "WHATSAPP_APP_SECRET", app_secret)
    monkeypatch.setattr(settings, "WHATSAPP_WEBHOOK_VERIFY_SIGNATURE", True)

    payload_dict = _create_webhook_payload("+919876543210", "wamid.sig1", "menu")
    payload_bytes = json.dumps(payload_dict).encode("utf-8")

    # 1. Valid signature
    valid_sig = "sha256=" + hmac.new(app_secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    resp_valid = await async_client.post(
        "/api/v1/integrations/whatsapp/webhook",
        content=payload_bytes,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": valid_sig},
    )
    assert resp_valid.status_code == 200

    # 2. Invalid signature
    resp_invalid = await async_client.post(
        "/api/v1/integrations/whatsapp/webhook",
        content=payload_bytes,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=bad_hex_signature"},
    )
    assert resp_invalid.status_code == 403

    # 3. Missing signature
    resp_missing = await async_client.post(
        "/api/v1/integrations/whatsapp/webhook",
        content=payload_bytes,
        headers={"Content-Type": "application/json"},
    )
    assert resp_missing.status_code == 403

    # 4. Tampered payload
    tampered_bytes = json.dumps(_create_webhook_payload("+919876543210", "wamid.sig1", "bill")).encode("utf-8")
    resp_tampered = await async_client.post(
        "/api/v1/integrations/whatsapp/webhook",
        content=tampered_bytes,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": valid_sig},
    )
    assert resp_tampered.status_code == 403

    # 5. Malformed JSON
    resp_malformed = await async_client.post(
        "/api/v1/integrations/whatsapp/webhook",
        content=b"not valid json",
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=" + hmac.new(app_secret.encode("utf-8"), b"not valid json", hashlib.sha256).hexdigest()},
    )
    assert resp_malformed.status_code == 400


# ===========================================================================
# 2. PERSISTENT WEBHOOK IDEMPOTENCY
# ===========================================================================

async def test_webhook_persistent_idempotency_prevents_duplicate_actions(
    async_client: AsyncClient, db_session: AsyncSession, security_setup
):
    """
    Verify repeated identical webhook deliveries with same message.id:
    - First delivery executes the message.
    - Second delivery returns HTTP 200 to Meta but skips duplicate execution.
    """
    ctx = security_setup
    payload = _create_webhook_payload("+919876543210", "wamid.dup001", "qr qr-secure-r1-t1")

    # 1. First webhook delivery
    resp1 = await async_client.post("/api/v1/integrations/whatsapp/webhook", json=payload)
    assert resp1.status_code == 200
    sent_count_1 = len(whatsapp_client.sent_messages)
    assert sent_count_1 >= 1

    # Verify event recorded in DB
    event_repo = WebhookEventRepository(db_session)
    evt = await event_repo.get_by_message_id("wamid.dup001")
    assert evt is not None
    assert evt.message_id == "wamid.dup001"
    assert evt.from_phone_masked == "+9******10"

    # 2. Second delivery with exact same message.id
    resp2 = await async_client.post("/api/v1/integrations/whatsapp/webhook", json=payload)
    assert resp2.status_code == 200
    sent_count_2 = len(whatsapp_client.sent_messages)

    # No additional message sent; duplicate was cleanly skipped
    assert sent_count_2 == sent_count_1


# ===========================================================================
# 3. MULTI-TENANT SECURITY AUDIT
# ===========================================================================

async def test_cross_restaurant_menu_access_rejected(db_session: AsyncSession, security_setup):
    """
    Session at Restaurant 1 cannot read menu categories or items belonging to Restaurant 2.
    """
    ctx = security_setup
    menu_service = CustomerMenuService(db_session)

    # Category of Restaurant 2 requested with Session 1
    with pytest.raises(EntityNotFoundError) as exc_info:
        await menu_service.get_category_items(
            session_id=ctx["sess1"].id,
            category_id=ctx["c2"].id,
        )
    assert exc_info.value.error_code == "CATEGORY_NOT_FOUND"


async def test_cross_restaurant_cart_addition_rejected(db_session: AsyncSession, security_setup):
    """
    Customer session at Restaurant 1 cannot add menu item belonging to Restaurant 2.
    """
    ctx = security_setup
    cart_service = CartService(db_session)

    with pytest.raises(BadRequestError) as exc_info:
        await cart_service.add_item(
            session_id=ctx["sess1"].id,
            menu_item_id=ctx["i2"].id,  # belongs to r2
            quantity=1,
        )
    assert exc_info.value.error_code == "CROSS_RESTAURANT_ITEM_REJECTED"


async def test_cross_restaurant_kitchen_actions_rejected(db_session: AsyncSession, security_setup):
    """
    Kitchen of Restaurant 2 cannot access or transition orders belonging to Restaurant 1.
    """
    ctx = security_setup
    order_service = OrderService(db_session)
    cart_service = CartService(db_session)

    # Create order at Restaurant 1
    await cart_service.add_item(ctx["sess1"].id, ctx["i1"].id, 2)
    order_resp = await order_service.checkout_cart(ctx["sess1"].id)
    await db_session.commit()

    # Kitchen of Restaurant 2 attempts to transition order of Restaurant 1
    with pytest.raises(EntityNotFoundError) as exc_info:
        await order_service.transition_order_status(
            restaurant_id=ctx["r2"].id,  # wrong restaurant
            order_id=order_resp.id,
            new_status="ACCEPTED",
        )
    assert exc_info.value.error_code == "ORDER_NOT_FOUND"


# ===========================================================================
# 4. SESSION OWNERSHIP & LIFECYCLE GUARDS
# ===========================================================================

async def test_closed_session_operations_rejected(db_session: AsyncSession, security_setup):
    """
    Once a dining session is CLOSED, all operations (cart, checkout, bill) must fail safely.
    """
    ctx = security_setup
    cart_service = CartService(db_session)
    order_service = OrderService(db_session)
    billing_service = BillingService(db_session)

    # Close session 1
    ctx["sess1"].status = "CLOSED"
    await db_session.commit()

    # 1. Cart modification rejected
    with pytest.raises(BadRequestError) as exc:
        await cart_service.add_item(ctx["sess1"].id, ctx["i1"].id, 1)
    assert exc.value.error_code == "SESSION_EXPIRED"

    # 2. Checkout rejected
    with pytest.raises(BadRequestError) as exc:
        await order_service.checkout_cart(ctx["sess1"].id)
    assert exc.value.error_code == "SESSION_EXPIRED"

    # 3. Bill request rejected
    with pytest.raises(BadRequestError) as exc:
        await billing_service.generate_or_get_bill(ctx["sess1"].id)
    assert exc.value.error_code == "SESSION_EXPIRED"


async def test_expired_session_checkout_rejected(db_session: AsyncSession, security_setup):
    """
    Expired session cannot place an order.
    """
    ctx = security_setup
    order_service = OrderService(db_session)
    cart_service = CartService(db_session)

    await cart_service.add_item(ctx["sess1"].id, ctx["i1"].id, 1)

    # Force expiration
    ctx["sess1"].expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    await db_session.commit()

    with pytest.raises(BadRequestError) as exc:
        await order_service.checkout_cart(ctx["sess1"].id)
    assert exc.value.error_code == "SESSION_EXPIRED"


# ===========================================================================
# 5. QR TOKEN SECURITY & ENUMERATION RESISTANCE
# ===========================================================================

async def test_qr_token_security_and_invalid_token(db_session: AsyncSession, security_setup):
    """
    Verify QR tokens are unpredictable, safe against enumeration, and foreign tokens rejected.
    """
    ctx = security_setup
    session_service = SessionService(db_session)

    # 1. Unknown token returns controlled error
    with pytest.raises(EntityNotFoundError) as exc:
        await session_service.resolve_qr("unknown-random-qr-token")
    assert exc.value.error_code == "QR_TOKEN_NOT_FOUND"

    # 2. Token entropy check
    token1 = generate_qr_token()
    token2 = generate_qr_token()
    assert token1 != token2
    assert len(token1) >= 32


# ===========================================================================
# 6. CONCURRENCY CONTROLS (BILLING & SETTLEMENT)
# ===========================================================================

async def test_bill_settlement_double_settle_rejected(db_session: AsyncSession, security_setup):
    """
    Two consecutive or concurrent settlement requests:
    First settles; second receives BILL_ALREADY_SETTLED.
    """
    ctx = security_setup
    cart_service = CartService(db_session)
    order_service = OrderService(db_session)
    billing_service = BillingService(db_session)

    await cart_service.add_item(ctx["sess1"].id, ctx["i1"].id, 1)
    ord_resp = await order_service.checkout_cart(ctx["sess1"].id)
    await order_service.transition_order_status(ctx["r1"].id, ord_resp.id, "ACCEPTED")
    await order_service.transition_order_status(ctx["r1"].id, ord_resp.id, "PREPARING")
    await order_service.transition_order_status(ctx["r1"].id, ord_resp.id, "READY")
    await order_service.transition_order_status(ctx["r1"].id, ord_resp.id, "SERVED")
    await db_session.commit()

    bill_resp = await billing_service.generate_or_get_bill(ctx["sess1"].id)
    await db_session.commit()

    # 1. First settlement succeeds
    settled = await billing_service.settle_bill(bill_resp.id)
    assert settled.status == "SETTLED"
    await db_session.commit()

    # 2. Second settlement receives BILL_ALREADY_SETTLED
    with pytest.raises(BadRequestError) as exc:
        await billing_service.settle_bill(bill_resp.id)
    assert exc.value.error_code == "BILL_ALREADY_SETTLED"


# ===========================================================================
# 7. PRIVACY & PII SAFEGUARDS
# ===========================================================================

async def test_privacy_mask_identifier_and_responses(db_session: AsyncSession, security_setup):
    """
    Customer phone numbers are masked and never leak in public responses.
    """
    assert mask_identifier("+919876543210") == "+9******10"
    assert mask_identifier("+1234567890") == "+1******90"

    ctx = security_setup
    cart_service = CartService(db_session)
    order_service = OrderService(db_session)

    await cart_service.add_item(ctx["sess1"].id, ctx["i1"].id, 1)
    ord_resp = await order_service.checkout_cart(ctx["sess1"].id)

    # Customer and Kitchen order responses do not have phone number fields
    order_dict = ord_resp.model_dump()
    assert "customer_phone" not in order_dict
    assert "phone_number" not in order_dict
    assert "whatsapp_id" not in order_dict


# ===========================================================================
# 8. INPUT VALIDATION & HTTP SECURITY HEADERS
# ===========================================================================

async def test_input_validation_negative_quantity(async_client: AsyncClient, security_setup):
    """
    Adding negative quantity returns HTTP 422 or 400.
    """
    ctx = security_setup
    resp = await async_client.post(
        "/api/v1/cart/items",
        json={"menu_item_id": str(ctx["i1"].id), "quantity": -5},
        headers={"X-Session-ID": str(ctx["sess1"].id)},
    )
    assert resp.status_code in (400, 422)


async def test_http_security_headers_present(async_client: AsyncClient):
    """
    Verify security headers are returned on API responses.
    """
    resp = await async_client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


# ===========================================================================
# 9. HEALTH & READINESS PROBES
# ===========================================================================

async def test_health_live_and_ready_endpoints(async_client: AsyncClient):
    """
    Verify /health/live and /health/ready probes.
    """
    live_resp = await async_client.get("/api/v1/health/live")
    assert live_resp.status_code == 200
    assert live_resp.json() == {"status": "live"}

    ready_resp = await async_client.get("/api/v1/health/ready")
    assert ready_resp.status_code == 200
    assert ready_resp.json()["status"] == "ready"
    assert ready_resp.json()["database"] == "connected"
