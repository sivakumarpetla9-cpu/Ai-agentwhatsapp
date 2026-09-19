import json
import logging
from unittest.mock import AsyncMock, patch
import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.integrations.whatsapp.client import (
    BaseWhatsAppClient,
    MetaWhatsAppClient,
    MockWhatsAppClient,
    WhatsAppClient,
    get_whatsapp_client,
    sanitize_sensitive_string,
)
from app.integrations.whatsapp.schemas import OutboundMessageRecord
from app.services.session import mask_identifier


# ---------------------------------------------------------------------------
# Unit Tests: Sanitization Helper
# ---------------------------------------------------------------------------

def test_sanitize_sensitive_string():
    raw = "Failed for +919876543210 with Bearer EAAXsecret12345 and secret secret_val"
    sanitized = sanitize_sensitive_string(raw, secret_values=["secret_val"])
    assert "+919876543210" not in sanitized
    assert "[MASKED_PHONE]" in sanitized
    assert "EAAXsecret12345" not in sanitized
    assert "Bearer [MASKED_TOKEN]" in sanitized
    assert "secret_val" not in sanitized
    assert "[MASKED_SECRET]" in sanitized


# ---------------------------------------------------------------------------
# Unit Tests: MockWhatsAppClient
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mock_client_send_and_clear():
    mock_client = MockWhatsAppClient()
    assert len(mock_client.sent_messages) == 0

    # 1. Text
    rec1 = await mock_client.send_text("+919876543210", "Hello customer")
    assert rec1.type == "text"
    assert rec1.body == "Hello customer"
    assert rec1.success is True
    assert len(mock_client.sent_messages) == 1

    # 2. Buttons
    rec2 = await mock_client.send_buttons(
        "+919876543210",
        "Select an option",
        [{"id": "BTN_1", "title": "Option 1"}],
    )
    assert rec2.type == "button"
    assert len(mock_client.sent_messages) == 2

    # 3. List
    rec3 = await mock_client.send_list(
        "+919876543210",
        "Browse categories",
        "View Categories",
        [{"title": "Section 1", "rows": [{"id": "ROW_1", "title": "Row 1"}]}],
    )
    assert rec3.type == "list"
    assert len(mock_client.sent_messages) == 3

    # 4. Clear
    mock_client.clear_sent_messages()
    assert len(mock_client.sent_messages) == 0


# ---------------------------------------------------------------------------
# Unit Tests: MetaWhatsAppClient - Payload Builders & HTTP Communication
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_meta_client_text_payload():
    captured_requests = []

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(
            status_code=200,
            json={
                "messaging_product": "whatsapp",
                "contacts": [{"input": "919876543210", "wa_id": "919876543210"}],
                "messages": [{"id": "wamid.HBgLMTIzNDU2Nzg5MA=="}],
            },
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        meta_client = MetaWhatsAppClient(
            access_token="test-access-token-123",
            phone_number_id="10000000001",
            api_url="https://graph.facebook.com/v21.0",
            http_client=http_client,
        )

        record = await meta_client.send_text("+919876543210", "Welcome to restaurant!")
        assert record.success is True
        assert record.meta_message_id == "wamid.HBgLMTIzNDU2Nzg5MA=="
        assert record.payload is not None

        # Verify HTTP request
        assert len(captured_requests) == 1
        req = captured_requests[0]
        assert req.method == "POST"
        assert req.url == "https://graph.facebook.com/v21.0/10000000001/messages"
        assert req.headers["Authorization"] == "Bearer test-access-token-123"
        assert req.headers["Content-Type"] == "application/json"

        body = json.loads(req.content)
        assert body["messaging_product"] == "whatsapp"
        assert body["recipient_type"] == "individual"
        assert body["to"] == "+919876543210"
        assert body["type"] == "text"
        assert body["text"]["body"] == "Welcome to restaurant!"


@pytest.mark.asyncio
async def test_meta_client_button_payload_truncation():
    captured_requests = []

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(
            status_code=200,
            json={"messages": [{"id": "wamid.btn123"}]},
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        meta_client = MetaWhatsAppClient(
            access_token="token-xyz",
            phone_number_id="12345",
            api_url="https://graph.facebook.com/v21.0",
            http_client=http_client,
        )

        buttons = [
            {"id": "BTN_1", "title": "This is a very long title that exceeds twenty chars"},
            {"id": "BTN_2", "title": "Short Title"},
            {"id": "BTN_3", "title": "Third Option"},
            {"id": "BTN_4", "title": "Fourth Option Should Be Dropped"},  # Meta limit is 3 buttons
        ]

        record = await meta_client.send_buttons("+919876543210", "Please choose:", buttons)
        assert record.success is True
        assert record.meta_message_id == "wamid.btn123"

        req_body = json.loads(captured_requests[0].content)
        assert req_body["type"] == "interactive"
        interactive = req_body["interactive"]
        assert interactive["type"] == "button"
        assert interactive["body"]["text"] == "Please choose:"
        btn_action = interactive["action"]["buttons"]

        # Meta rule: max 3 buttons
        assert len(btn_action) == 3
        # Meta rule: title truncated to 20 chars
        assert btn_action[0]["reply"]["title"] == "This is a very long "
        assert len(btn_action[0]["reply"]["title"]) <= 20


@pytest.mark.asyncio
async def test_meta_client_list_payload_formatting():
    captured_requests = []

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(
            status_code=200,
            json={"messages": [{"id": "wamid.list456"}]},
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        meta_client = MetaWhatsAppClient(
            access_token="token-xyz",
            phone_number_id="12345",
            api_url="https://graph.facebook.com/v21.0",
            http_client=http_client,
        )

        sections = [
            {
                "title": "Starters",
                "rows": [
                    {"id": "ITEM_1", "title": "Paneer Tikka", "description": "Grilled cottage cheese"},
                    {"id": "ITEM_2", "title": "Chicken 65", "description": "Spicy fried chicken"},
                ],
            }
        ]

        # Button label longer than 20 chars must be capped
        record = await meta_client.send_list(
            "+919876543210",
            "Select your dishes:",
            "View Full Restaurant Menu",
            sections,
        )
        assert record.success is True
        assert record.meta_message_id == "wamid.list456"

        req_body = json.loads(captured_requests[0].content)
        assert req_body["type"] == "interactive"
        interactive = req_body["interactive"]
        assert interactive["type"] == "list"
        assert interactive["action"]["button"] == "View Full Restaurant"
        assert len(interactive["action"]["button"]) <= 20
        assert interactive["action"]["sections"] == sections


# ---------------------------------------------------------------------------
# Unit Tests: MetaWhatsAppClient - Error & Timeout Handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_meta_client_handles_meta_api_error():
    async def error_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=400,
            json={
                "error": {
                    "message": "(#100) Param text[body] is required",
                    "type": "OAuthException",
                    "code": 100,
                    "fbtrace_id": "ABCxyz123",
                }
            },
        )

    transport = httpx.MockTransport(error_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        meta_client = MetaWhatsAppClient(
            access_token="secret-token",
            phone_number_id="12345",
            api_url="https://graph.facebook.com/v21.0",
            http_client=http_client,
        )

        record = await meta_client.send_text("+919876543210", "bad message")
        assert record.success is False
        assert "Meta API error" in record.error
        assert "code 100" in record.error
        assert "(#100) Param text[body] is required" in record.error
        # Token must never leak into error
        assert "secret-token" not in record.error


@pytest.mark.asyncio
async def test_meta_client_handles_timeout():
    async def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("Connection timed out", request=request)

    transport = httpx.MockTransport(timeout_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        meta_client = MetaWhatsAppClient(
            access_token="token-abc",
            phone_number_id="12345",
            api_url="https://graph.facebook.com/v21.0",
            timeout=5.0,
            http_client=http_client,
        )

        record = await meta_client.send_text("+919876543210", "hello")
        assert record.success is False
        assert "timed out after 5.0 seconds" in record.error


@pytest.mark.asyncio
async def test_meta_client_handles_network_failure():
    async def network_error_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("DNS lookup failed", request=request)

    transport = httpx.MockTransport(network_error_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        meta_client = MetaWhatsAppClient(
            access_token="token-abc",
            phone_number_id="12345",
            api_url="https://graph.facebook.com/v21.0",
            http_client=http_client,
        )

        record = await meta_client.send_text("+919876543210", "hello")
        assert record.success is False
        assert "Network error" in record.error
        assert "ConnectError" in record.error


@pytest.mark.asyncio
async def test_meta_client_missing_credentials_fails_cleanly():
    meta_client = MetaWhatsAppClient(
        access_token=None,
        phone_number_id=None,
    )
    record = await meta_client.send_text("+919876543210", "hello")
    assert record.success is False
    assert "credentials unconfigured" in record.error


# ---------------------------------------------------------------------------
# Unit Tests: Facade & Configuration Mode Switching
# ---------------------------------------------------------------------------

def test_facade_switches_modes():
    # Mock mode
    mock_facade = WhatsAppClient(mode="mock")
    assert isinstance(mock_facade._delegate, MockWhatsAppClient)

    # Meta mode
    meta_facade = WhatsAppClient(
        mode="meta",
        api_token="custom_token",
        phone_number_id="99999",
    )
    assert isinstance(meta_facade._delegate, MetaWhatsAppClient)
    assert meta_facade._delegate.access_token == "custom_token"


def test_settings_validation_meta_mode_requires_credentials():
    # Valid mock configuration succeeds without credentials
    cfg_mock = Settings(
        ENVIRONMENT="development",
        WHATSAPP_MODE="mock",
    )
    assert cfg_mock.WHATSAPP_USE_MOCK is True
    assert cfg_mock.is_meta_mode is False

    # WHATSAPP_MODE=meta without credentials fails validation
    with pytest.raises(ValueError, match="WHATSAPP_ACCESS_TOKEN .* must be configured when WHATSAPP_MODE='meta'"):
        Settings(
            ENVIRONMENT="development",
            WHATSAPP_MODE="meta",
            WHATSAPP_ACCESS_TOKEN=None,
            WHATSAPP_PHONE_NUMBER_ID=None,
            WHATSAPP_APP_SECRET=None,
        )

    # WHATSAPP_MODE=meta with required credentials succeeds
    cfg_meta = Settings(
        ENVIRONMENT="development",
        WHATSAPP_MODE="meta",
        WHATSAPP_ACCESS_TOKEN="valid-access-token-123",
        WHATSAPP_PHONE_NUMBER_ID="10000000002",
        WHATSAPP_APP_SECRET="valid-app-secret-456",
    )
    assert cfg_meta.WHATSAPP_USE_MOCK is False
    assert cfg_meta.is_meta_mode is True
    assert cfg_meta.effective_whatsapp_token == "valid-access-token-123"
    assert cfg_meta.effective_whatsapp_api_url == "https://graph.facebook.com/v21.0"


def test_settings_graph_api_version_normalization():
    cfg = Settings(
        ENVIRONMENT="development",
        WHATSAPP_MODE="mock",
        WHATSAPP_API_VERSION="v22.0",
    )
    assert cfg.effective_whatsapp_api_url == "https://graph.facebook.com/v22.0"

    cfg_no_v = Settings(
        ENVIRONMENT="development",
        WHATSAPP_MODE="mock",
        WHATSAPP_API_VERSION="26.0",
    )
    assert cfg_no_v.effective_whatsapp_api_url == "https://graph.facebook.com/v26.0"


# ---------------------------------------------------------------------------
# Integration Tests: WhatsAppBotEngine Flow B with MetaWhatsAppClient
# ---------------------------------------------------------------------------

from app.models.restaurant import Restaurant, RestaurantTable
from app.models.customer import Customer, CustomerSession
from app.models.order import Order, OrderStatus
from app.integrations.whatsapp.bot import WhatsAppBotEngine
from app.integrations.whatsapp.schemas import (
    WhatsAppInboundMessage,
    WhatsAppTextMessage,
    WhatsAppInteractive,
    WhatsAppInteractiveListReply,
)
from app.services.order_notifications import OrderNotificationService
from decimal import Decimal


@pytest.mark.asyncio
async def test_bot_direct_table_picker_flow_with_meta_client(db_session: AsyncSession):
    """
    Verify that WhatsAppBotEngine with MetaWhatsAppClient correctly:
    1. Handles greeting from user with no session.
    2. Translates table picker into a Meta interactive list message.
    3. Handles list reply callback to seat at table and starts session.
    """
    # 1. Seed restaurant & tables
    res = Restaurant(name="SpiceBox Grill", is_active=True)
    db_session.add(res)
    await db_session.flush()

    t1 = RestaurantTable(restaurant_id=res.id, table_number="T1", qr_token="qr-t1-meta", is_active=True)
    t2 = RestaurantTable(restaurant_id=res.id, table_number="T2", qr_token="qr-t2-meta", is_active=True)
    db_session.add_all([t1, t2])
    await db_session.flush()

    captured_requests = []

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(
            status_code=200,
            json={"messages": [{"id": "wamid.meta12345"}]},
        )

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        meta_client = MetaWhatsAppClient(
            access_token="test-meta-token",
            phone_number_id="10000000001",
            api_url="https://graph.facebook.com/v21.0",
            http_client=http_client,
        )

        bot = WhatsAppBotEngine(session=db_session, client=meta_client)

        # Step 1: User says 'hi' -> triggers Flow B table picker
        inbound_msg = WhatsAppInboundMessage(
            from_="+919876543210",
            id="msg_001",
            timestamp="1726732800",
            type="text",
            text=WhatsAppTextMessage(body="hi"),
        )
        await bot.handle_inbound_message("+919876543210", inbound_msg)

        assert len(captured_requests) == 1
        req_data = json.loads(captured_requests[0].content)
        assert req_data["type"] == "interactive"
        assert req_data["interactive"]["type"] == "list"
        assert req_data["interactive"]["action"]["button"] == "Select Table"
        sections = req_data["interactive"]["action"]["sections"]
        assert len(sections) == 1
        assert len(sections[0]["rows"]) == 2
        assert sections[0]["rows"][0]["id"] == f"SELECT_TABLE:{t1.id}"

        # Step 2: User selects Table 1
        callback_msg = WhatsAppInboundMessage(
            from_="+919876543210",
            id="msg_002",
            timestamp="1726732801",
            type="interactive",
            interactive=WhatsAppInteractive(
                type="list_reply",
                list_reply=WhatsAppInteractiveListReply(
                    id=f"SELECT_TABLE:{t1.id}",
                    title="T1",
                ),
            ),
        )
        await bot.handle_inbound_message("+919876543210", callback_msg)

        # Bot responds with welcome buttons and menu
        assert len(captured_requests) >= 2


@pytest.mark.asyncio
async def test_order_notifications_with_meta_client_success_and_failure(db_session: AsyncSession):
    """
    Verify OrderNotificationService dispatching through MetaWhatsAppClient:
    - 200 OK: Marks notification SENT with meta_message_id.
    - 500 Error: Marks notification FAILED with sanitized error, without raising exception.
    """
    res = Restaurant(name="SpiceBox Grill", is_active=True)
    db_session.add(res)
    await db_session.flush()

    t1 = RestaurantTable(restaurant_id=res.id, table_number="T1", qr_token="qr-t1-notif", is_active=True)
    db_session.add(t1)
    await db_session.flush()

    cust = Customer(whatsapp_customer_id="+919876543210", display_name="Test Customer")
    db_session.add(cust)
    await db_session.flush()

    sess = CustomerSession(
        restaurant_id=res.id,
        table_id=t1.id,
        customer_id=cust.id,
        status="ACTIVE",
    )
    db_session.add(sess)
    await db_session.flush()

    order = Order(
        restaurant_id=res.id,
        table_id=t1.id,
        customer_session_id=sess.id,
        status=OrderStatus.NEW.value,
        total_amount=Decimal("150.00"),
    )
    db_session.add(order)
    await db_session.flush()

    # Case A: Meta responds with 200 OK
    async def ok_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={"messages": [{"id": "wamid.success999"}]},
        )

    transport_ok = httpx.MockTransport(ok_handler)
    async with httpx.AsyncClient(transport=transport_ok) as http_client:
        meta_client_ok = MetaWhatsAppClient(
            access_token="test-token",
            phone_number_id="10000000001",
            api_url="https://graph.facebook.com/v21.0",
            http_client=http_client,
        )

        notif_service = OrderNotificationService(db_session, whatsapp_client=meta_client_ok)
        notif = await notif_service.send_kitchen_status_notification(
            order_id=order.id,
            new_status="ACCEPTED",
            restaurant_id=res.id,
        )

        assert notif is not None
        assert notif.delivery_status == "SENT"
        assert notif.error_message is None

    # Case B: Meta responds with 500 Internal Error
    async def fail_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=500,
            json={"error": {"message": "Internal Meta Graph API error", "code": 1}},
        )

    transport_fail = httpx.MockTransport(fail_handler)
    async with httpx.AsyncClient(transport=transport_fail) as http_client:
        meta_client_fail = MetaWhatsAppClient(
            access_token="test-token",
            phone_number_id="10000000001",
            api_url="https://graph.facebook.com/v21.0",
            http_client=http_client,
        )

        notif_service_fail = OrderNotificationService(db_session, whatsapp_client=meta_client_fail)
        notif_failed = await notif_service_fail.send_kitchen_status_notification(
            order_id=order.id,
            new_status="PREPARING",
            restaurant_id=res.id,
        )

        assert notif_failed is not None
        assert notif_failed.delivery_status == "FAILED"
        assert "Meta API error" in notif_failed.error_message
        # Order status must remain intact
        assert order.status == OrderStatus.NEW.value
