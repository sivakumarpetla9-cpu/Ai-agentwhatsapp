import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict
from unittest.mock import patch
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.whatsapp.client import whatsapp_client
from app.models.customer import Customer, CustomerSession
from app.models.menu import MenuCategory, MenuItem
from app.models.order import Order, OrderItem, OrderStatus, generate_order_number
from app.models.order_notification import OrderNotification
from app.models.restaurant import Restaurant, RestaurantTable
from app.services.order_notifications import OrderNotificationService, sanitize_message_error
from app.services.session import mask_identifier
from tests.test_whatsapp_webhook import make_webhook_payload


@pytest.fixture
async def notification_setup(db_session: AsyncSession):
    """
    Setup multi-restaurant fixtures for order notification testing.
    Restaurant 1: SpiceBox (Active)
    Restaurant 2: DragonWok (Active)
    """
    whatsapp_client.clear_sent_messages()

    # 1. Restaurants
    res1 = Restaurant(name="SpiceBox Dine-In", is_active=True)
    res2 = Restaurant(name="DragonWok", is_active=True)
    db_session.add_all([res1, res2])
    await db_session.flush()

    # 2. Tables
    t1 = RestaurantTable(restaurant_id=res1.id, table_number="Table 1", qr_token="qr-sp-t1", is_active=True)
    t2 = RestaurantTable(restaurant_id=res1.id, table_number="Table 2", qr_token="qr-sp-t2", is_active=True)
    t_res2 = RestaurantTable(restaurant_id=res2.id, table_number="Table 1", qr_token="qr-dw-t1", is_active=True)
    db_session.add_all([t1, t2, t_res2])
    await db_session.flush()

    # 3. Categories & Menu Items
    cat1 = MenuCategory(restaurant_id=res1.id, name="Biryani", display_order=1, is_active=True)
    db_session.add(cat1)
    await db_session.flush()

    item1 = MenuItem(
        restaurant_id=res1.id,
        category_id=cat1.id,
        name="Chicken Dum Biryani",
        price=Decimal("299.00"),
        is_available=True,
    )
    db_session.add(item1)
    await db_session.flush()

    # 4. Customers & Sessions
    cust1 = Customer(whatsapp_customer_id="+919876543210", display_name="Alice Customer")
    cust2 = Customer(whatsapp_customer_id="+919123456780", display_name="Bob Customer")
    db_session.add_all([cust1, cust2])
    await db_session.flush()

    sess1 = CustomerSession(
        customer_id=cust1.id,
        restaurant_id=res1.id,
        table_id=t1.id,
        status="ACTIVE",
    )
    sess2 = CustomerSession(
        customer_id=cust2.id,
        restaurant_id=res2.id,
        table_id=t_res2.id,
        status="ACTIVE",
    )
    db_session.add_all([sess1, sess2])
    await db_session.flush()

    # 5. Helper function to create an order
    async def create_order_for_session(
        session: CustomerSession,
        special_instructions: str = None,
        initial_status: str = OrderStatus.NEW.value,
    ) -> Order:
        order = Order(
            order_number=generate_order_number(),
            restaurant_id=session.restaurant_id,
            table_id=session.table_id,
            customer_session_id=session.id,
            status=initial_status,
            total_amount=Decimal("299.00"),
            special_instructions=special_instructions,
        )
        db_session.add(order)
        await db_session.flush()

        order_item = OrderItem(
            order_id=order.id,
            menu_item_id=item1.id,
            item_name="Chicken Dum Biryani",
            quantity=1,
            unit_price=Decimal("299.00"),
        )
        db_session.add(order_item)
        await db_session.commit()
        return order

    return {
        "restaurant1": res1,
        "restaurant2": res2,
        "table1": t1,
        "table2": t2,
        "table_res2": t_res2,
        "customer1": cust1,
        "customer2": cust2,
        "session1": sess1,
        "session2": sess2,
        "item1": item1,
        "create_order": create_order_for_session,
    }


# ---------------------------------------------------------------------------
# Test 1: ACCEPTED Sends WhatsApp Notification
# ---------------------------------------------------------------------------
async def test_1_accepted_sends_whatsapp_notification(
    async_client: AsyncClient, notification_setup
):
    ctx = notification_setup
    order = await ctx["create_order"](ctx["session1"])

    res = await async_client.patch(
        f"/api/v1/kitchen/orders/{order.id}/status",
        json={"restaurant_id": str(ctx["restaurant1"].id), "status": "ACCEPTED"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "ACCEPTED"

    # Verify WhatsApp notification was sent
    assert len(whatsapp_client.sent_messages) == 1
    msg = whatsapp_client.sent_messages[-1]
    assert msg.to == ctx["customer1"].whatsapp_customer_id
    assert f"Order {order.order_number}" in msg.body
    assert "Your order has been accepted by the restaurant." in msg.body
    assert "We\'ll start preparing it shortly." in msg.body


# ---------------------------------------------------------------------------
# Test 2: PREPARING Sends WhatsApp Notification
# ---------------------------------------------------------------------------
async def test_2_preparing_sends_whatsapp_notification(
    async_client: AsyncClient, notification_setup
):
    ctx = notification_setup
    order = await ctx["create_order"](ctx["session1"])

    # Transition to ACCEPTED first
    await async_client.patch(
        f"/api/v1/kitchen/orders/{order.id}/status",
        json={"restaurant_id": str(ctx["restaurant1"].id), "status": "ACCEPTED"},
    )
    whatsapp_client.clear_sent_messages()

    # Transition to PREPARING
    res = await async_client.patch(
        f"/api/v1/kitchen/orders/{order.id}/status",
        json={"restaurant_id": str(ctx["restaurant1"].id), "status": "PREPARING"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "PREPARING"

    assert len(whatsapp_client.sent_messages) == 1
    msg = whatsapp_client.sent_messages[-1]
    assert msg.to == ctx["customer1"].whatsapp_customer_id
    assert f"Order {order.order_number}" in msg.body
    assert "Your order is now being prepared." in msg.body


# ---------------------------------------------------------------------------
# Test 3: READY Sends WhatsApp Notification
# ---------------------------------------------------------------------------
async def test_3_ready_sends_whatsapp_notification(
    async_client: AsyncClient, notification_setup
):
    ctx = notification_setup
    order = await ctx["create_order"](ctx["session1"])

    await async_client.patch(
        f"/api/v1/kitchen/orders/{order.id}/status",
        json={"restaurant_id": str(ctx["restaurant1"].id), "status": "ACCEPTED"},
    )
    await async_client.patch(
        f"/api/v1/kitchen/orders/{order.id}/status",
        json={"restaurant_id": str(ctx["restaurant1"].id), "status": "PREPARING"},
    )
    whatsapp_client.clear_sent_messages()

    # Transition to READY
    res = await async_client.patch(
        f"/api/v1/kitchen/orders/{order.id}/status",
        json={"restaurant_id": str(ctx["restaurant1"].id), "status": "READY"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "READY"

    assert len(whatsapp_client.sent_messages) == 1
    msg = whatsapp_client.sent_messages[-1]
    assert msg.to == ctx["customer1"].whatsapp_customer_id
    assert f"Order {order.order_number}" in msg.body
    assert "Your order is ready." in msg.body
    assert "Please collect it from your table/service area." in msg.body


# ---------------------------------------------------------------------------
# Test 4: SERVED Sends WhatsApp Notification
# ---------------------------------------------------------------------------
async def test_4_served_sends_whatsapp_notification(
    async_client: AsyncClient, notification_setup
):
    ctx = notification_setup
    order = await ctx["create_order"](ctx["session1"])

    for st in ["ACCEPTED", "PREPARING", "READY"]:
        await async_client.patch(
            f"/api/v1/kitchen/orders/{order.id}/status",
            json={"restaurant_id": str(ctx["restaurant1"].id), "status": st},
        )
    whatsapp_client.clear_sent_messages()

    # Transition to SERVED
    res = await async_client.patch(
        f"/api/v1/kitchen/orders/{order.id}/status",
        json={"restaurant_id": str(ctx["restaurant1"].id), "status": "SERVED"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "SERVED"

    assert len(whatsapp_client.sent_messages) == 1
    msg = whatsapp_client.sent_messages[-1]
    assert msg.to == ctx["customer1"].whatsapp_customer_id
    assert f"Order {order.order_number}" in msg.body
    assert "Your order has been served." in msg.body
    assert "Thank you for dining with us!" in msg.body


# ---------------------------------------------------------------------------
# Test 5: CANCELLED Sends WhatsApp Notification
# ---------------------------------------------------------------------------
async def test_5_cancelled_sends_whatsapp_notification(
    async_client: AsyncClient, notification_setup
):
    ctx = notification_setup
    order = await ctx["create_order"](ctx["session1"])

    # Direct cancellation from NEW
    res = await async_client.patch(
        f"/api/v1/kitchen/orders/{order.id}/status",
        json={"restaurant_id": str(ctx["restaurant1"].id), "status": "CANCELLED"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "CANCELLED"

    assert len(whatsapp_client.sent_messages) == 1
    msg = whatsapp_client.sent_messages[-1]
    assert msg.to == ctx["customer1"].whatsapp_customer_id
    assert f"Order {order.order_number}" in msg.body
    assert "Your order has been cancelled." in msg.body
    assert "Please contact restaurant staff if you need assistance." in msg.body


# ---------------------------------------------------------------------------
# Test 6: NEW Does Not Send Customer Notification
# ---------------------------------------------------------------------------
async def test_6_new_does_not_send_notification(
    async_client: AsyncClient, notification_setup, db_session: AsyncSession
):
    ctx = notification_setup
    order = await ctx["create_order"](ctx["session1"])
    whatsapp_client.clear_sent_messages()

    # Order is in NEW status
    assert order.status == "NEW"

    # Notification service directly invoked for NEW returns None
    service = OrderNotificationService(db_session)
    res = await service.send_kitchen_status_notification(
        restaurant_id=ctx["restaurant1"].id,
        order_id=order.id,
        new_status="NEW",
    )
    assert res is None
    assert len(whatsapp_client.sent_messages) == 0


# ---------------------------------------------------------------------------
# Test 7: Invalid Status Transition Does Not Send Notification
# ---------------------------------------------------------------------------
async def test_7_invalid_status_transition_does_not_send_notification(
    async_client: AsyncClient, notification_setup
):
    ctx = notification_setup
    order = await ctx["create_order"](ctx["session1"])
    whatsapp_client.clear_sent_messages()

    # Attempt illegal transition: NEW -> READY
    res = await async_client.patch(
        f"/api/v1/kitchen/orders/{order.id}/status",
        json={"restaurant_id": str(ctx["restaurant1"].id), "status": "READY"},
    )
    assert res.status_code == 400
    assert len(whatsapp_client.sent_messages) == 0


# ---------------------------------------------------------------------------
# Test 8: Database Status Persists Even When WhatsApp Fails
# ---------------------------------------------------------------------------
async def test_8_database_status_persists_even_when_whatsapp_fails(
    async_client: AsyncClient, notification_setup, db_session: AsyncSession
):
    ctx = notification_setup
    order = await ctx["create_order"](ctx["session1"])

    with patch.object(
        whatsapp_client,
        "send_text",
        side_effect=RuntimeError("WhatsApp Meta API 500 Connection Timeout"),
    ):
        res = await async_client.patch(
            f"/api/v1/kitchen/orders/{order.id}/status",
            json={"restaurant_id": str(ctx["restaurant1"].id), "status": "ACCEPTED"},
        )

    # API response succeeds with HTTP 200
    assert res.status_code == 200
    assert res.json()["status"] == "ACCEPTED"

    # Database order status is persisted as ACCEPTED
    refreshed_order = await db_session.get(Order, order.id)
    assert refreshed_order.status == "ACCEPTED"


# ---------------------------------------------------------------------------
# Test 9: WhatsApp Failure Does Not Roll Back Order Status & Records Failure
# ---------------------------------------------------------------------------
async def test_9_whatsapp_failure_does_not_rollback_order_status(
    async_client: AsyncClient, notification_setup, db_session: AsyncSession
):
    ctx = notification_setup
    order = await ctx["create_order"](ctx["session1"])

    # Advance to ACCEPTED
    await async_client.patch(
        f"/api/v1/kitchen/orders/{order.id}/status",
        json={"restaurant_id": str(ctx["restaurant1"].id), "status": "ACCEPTED"},
    )

    # Now fail during PREPARING
    with patch.object(
        whatsapp_client,
        "send_text",
        side_effect=Exception("Network error for recipient +919876543210"),
    ):
        res = await async_client.patch(
            f"/api/v1/kitchen/orders/{order.id}/status",
            json={"restaurant_id": str(ctx["restaurant1"].id), "status": "PREPARING"},
        )

    assert res.status_code == 200
    assert res.json()["status"] == "PREPARING"

    # Verify notification record logged failure with sanitized error message
    stmt = select(OrderNotification).where(
        OrderNotification.order_id == order.id,
        OrderNotification.status == "PREPARING",
    )
    result = await db_session.execute(stmt)
    notif = result.scalars().first()
    assert notif is not None
    assert notif.delivery_status == "FAILED"
    # Ensure raw phone number was sanitized in error_message
    assert "+919876543210" not in notif.error_message
    assert "[MASKED_PHONE]" in notif.error_message


# ---------------------------------------------------------------------------
# Test 10 & 11: Idempotency Prevents Duplicate Outbound Notifications
# ---------------------------------------------------------------------------
async def test_10_and_11_duplicate_notification_is_idempotent(
    notification_setup, db_session: AsyncSession
):
    ctx = notification_setup
    order = await ctx["create_order"](ctx["session1"])

    service = OrderNotificationService(db_session)

    # First dispatch
    notif1 = await service.send_kitchen_status_notification(
        restaurant_id=ctx["restaurant1"].id,
        order_id=order.id,
        new_status="ACCEPTED",
    )
    assert notif1 is not None
    assert notif1.delivery_status == "SENT"
    assert len(whatsapp_client.sent_messages) == 1

    # Second dispatch for the exact same status
    notif2 = await service.send_kitchen_status_notification(
        restaurant_id=ctx["restaurant1"].id,
        order_id=order.id,
        new_status="ACCEPTED",
    )
    assert notif2 is not None
    assert notif2.id == notif1.id
    # No extra message was sent
    assert len(whatsapp_client.sent_messages) == 1

    # Verify only ONE record exists in DB for (order_id, ACCEPTED)
    stmt = select(OrderNotification).where(
        OrderNotification.order_id == order.id,
        OrderNotification.status == "ACCEPTED",
    )
    records = list((await db_session.execute(stmt)).scalars().all())
    assert len(records) == 1


# ---------------------------------------------------------------------------
# Test 12: Correct Order Number Appears in Message
# ---------------------------------------------------------------------------
async def test_12_correct_order_number_appears_in_message(
    async_client: AsyncClient, notification_setup
):
    ctx = notification_setup
    order = await ctx["create_order"](ctx["session1"])

    await async_client.patch(
        f"/api/v1/kitchen/orders/{order.id}/status",
        json={"restaurant_id": str(ctx["restaurant1"].id), "status": "ACCEPTED"},
    )
    msg = whatsapp_client.sent_messages[-1]
    assert f"Order {order.order_number}" in msg.body


# ---------------------------------------------------------------------------
# Test 13: Customer Identity Resolves Through Session Correctly
# ---------------------------------------------------------------------------
async def test_13_customer_identity_resolves_through_session(
    async_client: AsyncClient, notification_setup
):
    ctx = notification_setup
    order = await ctx["create_order"](ctx["session1"])

    await async_client.patch(
        f"/api/v1/kitchen/orders/{order.id}/status",
        json={"restaurant_id": str(ctx["restaurant1"].id), "status": "ACCEPTED"},
    )
    msg = whatsapp_client.sent_messages[-1]
    assert msg.to == ctx["customer1"].whatsapp_customer_id


# ---------------------------------------------------------------------------
# Test 14: Customer WhatsApp Identity Not Exposed in Kitchen API
# ---------------------------------------------------------------------------
async def test_14_customer_identity_not_exposed_in_kitchen_api(
    async_client: AsyncClient, notification_setup
):
    ctx = notification_setup
    order = await ctx["create_order"](ctx["session1"])

    res = await async_client.patch(
        f"/api/v1/kitchen/orders/{order.id}/status",
        json={"restaurant_id": str(ctx["restaurant1"].id), "status": "ACCEPTED"},
    )
    assert res.status_code == 200
    data = res.json()

    # Raw phone number must never be in any key or value
    phone = ctx["customer1"].whatsapp_customer_id
    assert phone not in str(data)
    assert "whatsapp" not in str(data).lower()
    assert "phone" not in str(data).lower()


# ---------------------------------------------------------------------------
# Test 15: Privacy & Masking Helpers
# ---------------------------------------------------------------------------
def test_15_privacy_and_error_masking():
    raw_phone = "+919876543210"
    masked = mask_identifier(raw_phone)
    assert masked == "+9******10"
    assert raw_phone not in masked

    error_with_phone = "Connection dropped while sending message to +919876543210 via Meta"
    sanitized = sanitize_message_error(error_with_phone)
    assert raw_phone not in sanitized
    assert "[MASKED_PHONE]" in sanitized


# ---------------------------------------------------------------------------
# Test 16: Cross-Restaurant Notification Isolation
# ---------------------------------------------------------------------------
async def test_16_cross_restaurant_notification_isolation(
    async_client: AsyncClient, notification_setup, db_session: AsyncSession
):
    ctx = notification_setup
    order_res1 = await ctx["create_order"](ctx["session1"])
    whatsapp_client.clear_sent_messages()

    # Restaurant 2 tries to transition Restaurant 1's order
    res = await async_client.patch(
        f"/api/v1/kitchen/orders/{order_res1.id}/status",
        json={"restaurant_id": str(ctx["restaurant2"].id), "status": "ACCEPTED"},
    )
    assert res.status_code == 404
    assert len(whatsapp_client.sent_messages) == 0

    # NotificationService direct cross-tenant check
    service = OrderNotificationService(db_session)
    notif = await service.send_kitchen_status_notification(
        restaurant_id=ctx["restaurant2"].id,
        order_id=order_res1.id,
        new_status="ACCEPTED",
    )
    assert notif is None
    assert len(whatsapp_client.sent_messages) == 0


# ---------------------------------------------------------------------------
# Test 17: Closed/Invalid Session Handled Safely
# ---------------------------------------------------------------------------
async def test_17_closed_session_handled_safely(
    notification_setup, db_session: AsyncSession
):
    ctx = notification_setup
    order = await ctx["create_order"](ctx["session1"])
    # Close session
    ctx["session1"].status = "CLOSED"
    await db_session.commit()

    service = OrderNotificationService(db_session)
    notif = await service.send_kitchen_status_notification(
        restaurant_id=ctx["restaurant1"].id,
        order_id=order.id,
        new_status="ACCEPTED",
    )
    # Safely skipped
    assert notif is None
    assert len(whatsapp_client.sent_messages) == 0


# ---------------------------------------------------------------------------
# Test 18: Mock WhatsApp Client Captures Outbound Notifications Accurately
# ---------------------------------------------------------------------------
async def test_18_mock_whatsapp_client_captures_outbound_notification(
    async_client: AsyncClient, notification_setup
):
    ctx = notification_setup
    order = await ctx["create_order"](ctx["session1"])

    await async_client.patch(
        f"/api/v1/kitchen/orders/{order.id}/status",
        json={"restaurant_id": str(ctx["restaurant1"].id), "status": "ACCEPTED"},
    )
    assert len(whatsapp_client.sent_messages) == 1
    record = whatsapp_client.sent_messages[0]
    assert record.to == ctx["customer1"].whatsapp_customer_id
    assert record.type == "text"
    assert "accepted by the restaurant" in record.body


# ---------------------------------------------------------------------------
# Test 19: Multiple Orders for Same Customer Notify Independently
# ---------------------------------------------------------------------------
async def test_19_multiple_orders_notify_independently(
    async_client: AsyncClient, notification_setup
):
    ctx = notification_setup
    order1 = await ctx["create_order"](ctx["session1"])
    order2 = await ctx["create_order"](ctx["session1"])
    whatsapp_client.clear_sent_messages()

    # Accept Order 1
    await async_client.patch(
        f"/api/v1/kitchen/orders/{order1.id}/status",
        json={"restaurant_id": str(ctx["restaurant1"].id), "status": "ACCEPTED"},
    )
    assert len(whatsapp_client.sent_messages) == 1
    assert f"Order {order1.order_number}" in whatsapp_client.sent_messages[0].body

    # Accept Order 2
    await async_client.patch(
        f"/api/v1/kitchen/orders/{order2.id}/status",
        json={"restaurant_id": str(ctx["restaurant1"].id), "status": "ACCEPTED"},
    )
    assert len(whatsapp_client.sent_messages) == 2
    assert f"Order {order2.order_number}" in whatsapp_client.sent_messages[1].body


# ---------------------------------------------------------------------------
# Test 20-23: Billing & Settlement Compatibility
# ---------------------------------------------------------------------------
async def test_20_23_billing_and_settlement_remain_intact(
    async_client: AsyncClient, notification_setup, db_session: AsyncSession
):
    ctx = notification_setup
    order = await ctx["create_order"](ctx["session1"])

    # Progress through lifecycle
    for st in ["ACCEPTED", "PREPARING", "READY", "SERVED"]:
        res = await async_client.patch(
            f"/api/v1/kitchen/orders/{order.id}/status",
            json={"restaurant_id": str(ctx["restaurant1"].id), "status": st},
        )
        assert res.status_code == 200

    # Ready & Served do NOT automatically close the session
    refreshed_sess = await db_session.get(CustomerSession, ctx["session1"].id)
    assert refreshed_sess.status == "ACTIVE"

    # Generate bill via POST /api/v1/billing/generate
    bill_res = await async_client.post(
        "/api/v1/billing/generate",
        json={"session_id": str(ctx["session1"].id)},
    )
    assert bill_res.status_code == 200
    bill_data = bill_res.json()
    assert bill_data["status"] == "OPEN"
    assert Decimal(bill_data["subtotal"]) == Decimal("299.00")

    # Settle bill via POST /api/v1/billing/{bill_id}/settle
    settle_res = await async_client.post(
        f"/api/v1/billing/{bill_data['id']}/settle",
        json={
            "session_id": str(ctx["session1"].id),
            "restaurant_id": str(ctx["restaurant1"].id),
        },
    )
    assert settle_res.status_code == 200
    settle_data = settle_res.json()
    assert settle_data["status"] == "SETTLED"

    # Verify session closed and table released
    refreshed_sess2 = await db_session.get(CustomerSession, ctx["session1"].id)
    assert refreshed_sess2.status == "CLOSED"


# ---------------------------------------------------------------------------
# Test 24: Full Realistic Dining & WhatsApp Notification Flow
# ---------------------------------------------------------------------------
async def test_24_full_realistic_dining_and_notification_flow(
    async_client: AsyncClient, notification_setup, db_session: AsyncSession
):
    """
    Realistic end-to-end integration:
    QR scan -> Session -> Add to Cart -> Checkout -> Kitchen ACCEPTED -> PREPARING -> READY -> SERVED -> Bill -> Settle
    """
    ctx = notification_setup
    from_phone = "+919999888877"

    # 1. Flow A: Customer scans Table 1 QR
    await async_client.post(
        "/api/v1/integrations/whatsapp/webhook",
        json=make_webhook_payload(
            from_phone=from_phone,
            message_type="text",
            text_body=f"START {ctx['table1'].qr_token}",
        ),
    )

    # 2. Add Biryani to cart
    await async_client.post(
        "/api/v1/integrations/whatsapp/webhook",
        json=make_webhook_payload(
            from_phone=from_phone,
            message_type="interactive",
            list_id=f"ADD_ITEM:{ctx['item1'].id}:2",
        ),
    )

    # 3. Checkout
    await async_client.post(
        "/api/v1/integrations/whatsapp/webhook",
        json=make_webhook_payload(
            from_phone=from_phone,
            message_type="interactive",
            button_id="CHECKOUT",
        ),
    )

    # Fetch placed order from kitchen queue
    k_res = await async_client.get(
        f"/api/v1/kitchen/orders?restaurant_id={ctx['restaurant1'].id}"
    )
    assert k_res.status_code == 200
    kitchen_orders = k_res.json()
    assert len(kitchen_orders) >= 1
    placed_order = kitchen_orders[-1]
    order_id = placed_order["id"]
    order_num = placed_order["order_number"]

    # 4. Kitchen ACCEPTED
    whatsapp_client.clear_sent_messages()
    res_acc = await async_client.patch(
        f"/api/v1/kitchen/orders/{order_id}/status",
        json={"restaurant_id": str(ctx["restaurant1"].id), "status": "ACCEPTED"},
    )
    assert res_acc.status_code == 200
    assert len(whatsapp_client.sent_messages) == 1
    assert "accepted by the restaurant" in whatsapp_client.sent_messages[0].body
    assert order_num in whatsapp_client.sent_messages[0].body

    # 5. Kitchen PREPARING
    whatsapp_client.clear_sent_messages()
    res_prep = await async_client.patch(
        f"/api/v1/kitchen/orders/{order_id}/status",
        json={"restaurant_id": str(ctx["restaurant1"].id), "status": "PREPARING"},
    )
    assert res_prep.status_code == 200
    assert len(whatsapp_client.sent_messages) == 1
    assert "is now being prepared" in whatsapp_client.sent_messages[0].body

    # 6. Kitchen READY
    whatsapp_client.clear_sent_messages()
    res_rdy = await async_client.patch(
        f"/api/v1/kitchen/orders/{order_id}/status",
        json={"restaurant_id": str(ctx["restaurant1"].id), "status": "READY"},
    )
    assert res_rdy.status_code == 200
    assert len(whatsapp_client.sent_messages) == 1
    assert "order is ready" in whatsapp_client.sent_messages[0].body

    # 7. Kitchen SERVED
    whatsapp_client.clear_sent_messages()
    res_srv = await async_client.patch(
        f"/api/v1/kitchen/orders/{order_id}/status",
        json={"restaurant_id": str(ctx["restaurant1"].id), "status": "SERVED"},
    )
    assert res_srv.status_code == 200
    assert len(whatsapp_client.sent_messages) == 1
    assert "order has been served" in whatsapp_client.sent_messages[0].body

    # 8. Customer requests bill via WhatsApp
    whatsapp_client.clear_sent_messages()
    await async_client.post(
        "/api/v1/integrations/whatsapp/webhook",
        json=make_webhook_payload(
            from_phone=from_phone,
            message_type="text",
            text_body="bill",
        ),
    )
    assert "Bill: BILL-" in whatsapp_client.sent_messages[0].body
    assert "Total: ₹" in whatsapp_client.sent_messages[0].body

    # 9. Get Session ID and Settle
    cust_obj = (
        await db_session.execute(
            select(Customer).where(Customer.whatsapp_customer_id == from_phone)
        )
    ).scalars().first()
    sess_obj = (
        await db_session.execute(
            select(CustomerSession).where(
                CustomerSession.customer_id == cust_obj.id,
                CustomerSession.status == "ACTIVE",
            )
        )
    ).scalars().first()

    bill_gen = await async_client.post(
        "/api/v1/billing/generate",
        json={"session_id": str(sess_obj.id)},
    )
    assert bill_gen.status_code == 200
    b_id = bill_gen.json()["id"]

    settle_res = await async_client.post(
        f"/api/v1/billing/{b_id}/settle",
        json={
            "session_id": str(sess_obj.id),
            "restaurant_id": str(ctx["restaurant1"].id),
        },
    )
    assert settle_res.status_code == 200
    assert settle_res.json()["status"] == "SETTLED"

    # Verify session closed and table released
    refreshed_sess_obj = await db_session.get(CustomerSession, sess_obj.id)
    assert refreshed_sess_obj.status == "CLOSED"
