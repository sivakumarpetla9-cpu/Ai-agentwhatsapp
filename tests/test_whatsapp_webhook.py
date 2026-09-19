import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Optional
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.whatsapp.client import whatsapp_client
from app.models.menu import MenuCategory, MenuItem
from app.models.restaurant import Restaurant, RestaurantTable


@pytest.fixture
async def webhook_test_setup(db_session: AsyncSession):
    """
    Seed test restaurant, table with QR token, categories, and menu items.
    """
    whatsapp_client.clear_sent_messages()

    # 1. Restaurant
    res = Restaurant(name="SpiceBox Dine-In", is_active=True)
    db_session.add(res)
    await db_session.flush()

    # 2. Tables
    t1 = RestaurantTable(
        restaurant_id=res.id, table_number="Table 1", qr_token="qr-token-table-1"
    )
    t2 = RestaurantTable(
        restaurant_id=res.id, table_number="Table 2", qr_token="qr-token-table-2"
    )
    db_session.add_all([t1, t2])
    await db_session.flush()

    # 3. Category & Items
    cat_biryani = MenuCategory(
        restaurant_id=res.id, name="Dum Biryani", display_order=1, is_active=True
    )
    cat_starters = MenuCategory(
        restaurant_id=res.id, name="Starters", display_order=2, is_active=True
    )
    db_session.add_all([cat_biryani, cat_starters])
    await db_session.flush()

    item_biryani = MenuItem(
        restaurant_id=res.id,
        category_id=cat_biryani.id,
        name="Chicken Dum Biryani",
        price=Decimal("299.00"),
        is_available=True,
    )
    item_tikka = MenuItem(
        restaurant_id=res.id,
        category_id=cat_starters.id,
        name="Paneer Tikka",
        price=Decimal("210.00"),
        is_available=True,
    )
    db_session.add_all([item_biryani, item_tikka])
    await db_session.commit()

    return {
        "restaurant": res,
        "table1": t1,
        "table2": t2,
        "cat_biryani": cat_biryani,
        "cat_starters": cat_starters,
        "item_biryani": item_biryani,
        "item_tikka": item_tikka,
    }


def make_webhook_payload(
    from_phone: str,
    message_type: str = "text",
    text_body: str = "",
    button_id: str = "",
    list_id: str = "",
    display_name: str = "Test Customer",
    message_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Helper to construct standard Meta WhatsApp Cloud API inbound webhook payloads.
    """
    msg_obj: Dict[str, Any] = {
        "from": from_phone,
        "id": message_id or f"wamid.{uuid.uuid4().hex}",
        "timestamp": "1726732800",
        "type": message_type,
    }

    if message_type == "text":
        msg_obj["text"] = {"body": text_body}
    elif message_type == "interactive":
        if button_id:
            msg_obj["interactive"] = {
                "type": "button_reply",
                "button_reply": {"id": button_id, "title": "Button Title"},
            }
        elif list_id:
            msg_obj["interactive"] = {
                "type": "list_reply",
                "list_reply": {"id": list_id, "title": "List Row Title"},
            }

    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WHATSAPP_BUSINESS_ACCOUNT_ID",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "+16505551111",
                                "phone_number_id": "100000000001",
                            },
                            "contacts": [
                                {
                                    "profile": {"name": display_name},
                                    "wa_id": from_phone.replace("+", ""),
                                }
                            ],
                            "messages": [msg_obj],
                        },
                    }
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# Test 1: Webhook Subscription Verification (Handshake)
# ---------------------------------------------------------------------------
async def test_1_webhook_verification_handshake(async_client: AsyncClient):
    # Valid token
    res = await async_client.get(
        "/api/v1/integrations/whatsapp/webhook"
        "?hub.mode=subscribe"
        "&hub.verify_token=dine_in_webhook_verify_token"
        "&hub.challenge=1158201444"
    )
    assert res.status_code == 200
    assert res.text == "1158201444"

    # Invalid token returns 403
    bad_res = await async_client.get(
        "/api/v1/integrations/whatsapp/webhook"
        "?hub.mode=subscribe"
        "&hub.verify_token=wrong_token"
        "&hub.challenge=1158201444"
    )
    assert bad_res.status_code == 403


# ---------------------------------------------------------------------------
# Test 2: Flow A - Customer Scans Table QR Code
# ---------------------------------------------------------------------------
async def test_2_flow_a_table_qr_scan_entry(
    async_client: AsyncClient, webhook_test_setup
):
    ctx = webhook_test_setup
    from_phone = "+919988776655"

    # Customer scans Table 1 QR: sends "START qr-token-table-1"
    payload = make_webhook_payload(
        from_phone=from_phone,
        message_type="text",
        text_body=f"START {ctx['table1'].qr_token}",
    )
    res = await async_client.post(
        "/api/v1/integrations/whatsapp/webhook", json=payload
    )
    assert res.status_code == 200

    # Verify bot dispatched welcome and categories list
    assert len(whatsapp_client.sent_messages) >= 1
    sent = whatsapp_client.sent_messages[-1]
    assert sent.type == "list"
    assert "Table 1" in sent.body
    assert "SpiceBox Dine-In" in sent.body
    assert any(
        row["title"] == "Dum Biryani"
        for sec in sent.sections  # type: ignore[union-attr]
        for row in sec["rows"]
    )


# ---------------------------------------------------------------------------
# Test 3: Flow B - Direct WhatsApp Message -> Table Selection List
# ---------------------------------------------------------------------------
async def test_3_flow_b_direct_message_table_selection(
    async_client: AsyncClient, webhook_test_setup
):
    ctx = webhook_test_setup
    from_phone = "+919988776644"

    # Customer says "Hi" without scanning QR
    payload1 = make_webhook_payload(
        from_phone=from_phone, message_type="text", text_body="Hi! I want to order."
    )
    await async_client.post("/api/v1/integrations/whatsapp/webhook", json=payload1)

    # Bot replies with Table Selection List
    assert len(whatsapp_client.sent_messages) == 1
    sent_list = whatsapp_client.sent_messages[-1]
    assert sent_list.type == "list"
    assert "select your dining table" in sent_list.body.lower()

    # Customer selects Table 2
    table2_id = str(ctx["table2"].id)
    payload2 = make_webhook_payload(
        from_phone=from_phone,
        message_type="interactive",
        list_id=f"SELECT_TABLE:{table2_id}",
    )
    await async_client.post("/api/v1/integrations/whatsapp/webhook", json=payload2)

    # Bot confirms Table 2 session and sends Menu Categories
    assert len(whatsapp_client.sent_messages) == 2
    sent_categories = whatsapp_client.sent_messages[-1]
    assert sent_categories.type == "list"
    assert "Table 2" in sent_categories.body


# ---------------------------------------------------------------------------
# Test 4: Menu Navigation & Adding Items to Cart
# ---------------------------------------------------------------------------
async def test_4_menu_navigation_and_add_to_cart(
    async_client: AsyncClient, webhook_test_setup
):
    ctx = webhook_test_setup
    from_phone = "+919988776633"

    # 1. Establish session via Table 1 QR
    await async_client.post(
        "/api/v1/integrations/whatsapp/webhook",
        json=make_webhook_payload(
            from_phone=from_phone, text_body=f"START {ctx['table1'].qr_token}"
        ),
    )

    # 2. Customer selects Dum Biryani category: VIEW_CAT:<cat_id>
    cat_id = str(ctx["cat_biryani"].id)
    await async_client.post(
        "/api/v1/integrations/whatsapp/webhook",
        json=make_webhook_payload(
            from_phone=from_phone,
            message_type="interactive",
            list_id=f"VIEW_CAT:{cat_id}",
        ),
    )

    # Bot sends list of dishes with ADD_ITEM buttons
    dish_list_msg = whatsapp_client.sent_messages[-1]
    assert dish_list_msg.type == "list"
    assert "Select an item to add" in dish_list_msg.body

    # 3. Customer adds Chicken Dum Biryani (x2): ADD_ITEM:<item_id>:2
    item_id = str(ctx["item_biryani"].id)
    await async_client.post(
        "/api/v1/integrations/whatsapp/webhook",
        json=make_webhook_payload(
            from_phone=from_phone,
            message_type="interactive",
            list_id=f"ADD_ITEM:{item_id}:2",
        ),
    )

    # Bot confirms addition and shows updated subtotal
    cart_added_msg = whatsapp_client.sent_messages[-1]
    assert cart_added_msg.type == "button"
    assert "Chicken Dum Biryani" in cart_added_msg.body
    assert "598.00" in cart_added_msg.body


# ---------------------------------------------------------------------------
# Test 5: View Cart and Clear Cart
# ---------------------------------------------------------------------------
async def test_5_view_cart_and_clear_cart(
    async_client: AsyncClient, webhook_test_setup
):
    ctx = webhook_test_setup
    from_phone = "+919988776622"

    # QR Scan & Add Tikka
    await async_client.post(
        "/api/v1/integrations/whatsapp/webhook",
        json=make_webhook_payload(
            from_phone=from_phone, text_body=f"START {ctx['table1'].qr_token}"
        ),
    )
    tikka_id = str(ctx["item_tikka"].id)
    await async_client.post(
        "/api/v1/integrations/whatsapp/webhook",
        json=make_webhook_payload(
            from_phone=from_phone,
            message_type="interactive",
            list_id=f"ADD_ITEM:{tikka_id}:1",
        ),
    )

    # View Cart
    await async_client.post(
        "/api/v1/integrations/whatsapp/webhook",
        json=make_webhook_payload(
            from_phone=from_phone,
            message_type="interactive",
            button_id="VIEW_CART",
        ),
    )
    cart_msg = whatsapp_client.sent_messages[-1]
    assert "Paneer Tikka" in cart_msg.body
    assert "210.00" in cart_msg.body

    # Clear Cart
    await async_client.post(
        "/api/v1/integrations/whatsapp/webhook",
        json=make_webhook_payload(
            from_phone=from_phone,
            message_type="interactive",
            button_id="CLEAR_CART",
        ),
    )
    cleared_msg = whatsapp_client.sent_messages[-1]
    assert "cleared" in cleared_msg.body.lower()


# ---------------------------------------------------------------------------
# Test 6: Checkout Places Order and Generates Order #XXXXXX
# ---------------------------------------------------------------------------
async def test_6_checkout_places_order_and_notifies_kitchen(
    async_client: AsyncClient, webhook_test_setup
):
    ctx = webhook_test_setup
    from_phone = "+919988776611"

    # 1. Scan QR and Add Biryani
    await async_client.post(
        "/api/v1/integrations/whatsapp/webhook",
        json=make_webhook_payload(
            from_phone=from_phone, text_body=f"START {ctx['table1'].qr_token}"
        ),
    )
    b_id = str(ctx["item_biryani"].id)
    await async_client.post(
        "/api/v1/integrations/whatsapp/webhook",
        json=make_webhook_payload(
            from_phone=from_phone,
            message_type="interactive",
            list_id=f"ADD_ITEM:{b_id}:1",
        ),
    )

    # 2. Checkout
    await async_client.post(
        "/api/v1/integrations/whatsapp/webhook",
        json=make_webhook_payload(
            from_phone=from_phone,
            message_type="interactive",
            button_id="CHECKOUT",
        ),
    )

    # Bot confirms placed order
    order_confirm_msg = whatsapp_client.sent_messages[-1]
    assert "Order #ORD-" in order_confirm_msg.body
    assert "Status*: *NEW*" in order_confirm_msg.body
    assert "299.00" in order_confirm_msg.body
    assert "Table 1" in order_confirm_msg.body

    # Verify kitchen queue has this order
    res_id = str(ctx["restaurant"].id)
    k_res = await async_client.get(f"/api/v1/kitchen/orders?restaurant_id={res_id}")
    assert k_res.status_code == 200
    k_orders = k_res.json()
    assert len(k_orders) == 1
    assert k_orders[0]["status"] == "NEW"
    assert k_orders[0]["table_number"] == "Table 1"


# ---------------------------------------------------------------------------
# Test 7: Order Status Check via WhatsApp
# ---------------------------------------------------------------------------
async def test_7_order_status_check(async_client: AsyncClient, webhook_test_setup):
    ctx = webhook_test_setup
    from_phone = "+919988776600"
    res_id = str(ctx["restaurant"].id)

    # Place order
    await async_client.post(
        "/api/v1/integrations/whatsapp/webhook",
        json=make_webhook_payload(
            from_phone=from_phone, text_body=f"START {ctx['table1'].qr_token}"
        ),
    )
    await async_client.post(
        "/api/v1/integrations/whatsapp/webhook",
        json=make_webhook_payload(
            from_phone=from_phone,
            message_type="interactive",
            list_id=f"ADD_ITEM:{ctx['item_biryani'].id}:1",
        ),
    )
    await async_client.post(
        "/api/v1/integrations/whatsapp/webhook",
        json=make_webhook_payload(
            from_phone=from_phone,
            message_type="interactive",
            button_id="CHECKOUT",
        ),
    )

    # Kitchen advances to PREPARING
    k_orders = (
        await async_client.get(f"/api/v1/kitchen/orders?restaurant_id={res_id}")
    ).json()
    order_id = k_orders[0]["id"]
    await async_client.patch(
        f"/api/v1/kitchen/orders/{order_id}/status",
        json={"restaurant_id": res_id, "status": "ACCEPTED"},
    )
    await async_client.patch(
        f"/api/v1/kitchen/orders/{order_id}/status",
        json={"restaurant_id": res_id, "status": "PREPARING"},
    )

    # Customer asks for status: "status" text or ORDER_STATUS button
    await async_client.post(
        "/api/v1/integrations/whatsapp/webhook",
        json=make_webhook_payload(
            from_phone=from_phone, message_type="text", text_body="status"
        ),
    )
    status_msg = whatsapp_client.sent_messages[-1]
    assert "PREPARING" in status_msg.body
