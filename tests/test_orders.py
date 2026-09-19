import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cart import Cart, CartItem
from app.models.customer import Customer, CustomerSession
from app.models.menu import MenuCategory, MenuItem
from app.models.order import Order, OrderItem, OrderStatus
from app.models.restaurant import Restaurant, RestaurantTable


@pytest.fixture
async def order_test_setup(db_session: AsyncSession):
    """
    Setup multi-restaurant fixtures for order checkout and kitchen testing.
    Restaurant 1: SpiceBox (Active)
    Restaurant 2: DragonWok (Active)
    """
    # 1. Restaurants
    res1 = Restaurant(name="SpiceBox", is_active=True)
    res2 = Restaurant(name="DragonWok", is_active=True)
    res_closed = Restaurant(name="NightKitchen", is_active=False)
    db_session.add_all([res1, res2, res_closed])
    await db_session.flush()

    # 2. Tables
    t1 = RestaurantTable(restaurant_id=res1.id, table_number="Table 1", qr_token="qr-sp-t1")
    t2 = RestaurantTable(restaurant_id=res2.id, table_number="Table 2", qr_token="qr-dw-t2")
    t_closed = RestaurantTable(restaurant_id=res_closed.id, table_number="Table 1", qr_token="qr-nk-t1")
    db_session.add_all([t1, t2, t_closed])
    await db_session.flush()

    # 3. Categories
    cat1 = MenuCategory(restaurant_id=res1.id, name="Biryani", display_order=1, is_active=True)
    cat2 = MenuCategory(restaurant_id=res2.id, name="Noodles", display_order=1, is_active=True)
    db_session.add_all([cat1, cat2])
    await db_session.flush()

    # 4. Menu Items
    biryani = MenuItem(
        restaurant_id=res1.id,
        category_id=cat1.id,
        name="Chicken Dum Biryani",
        price=Decimal("299.00"),
        is_available=True,
    )
    kebab = MenuItem(
        restaurant_id=res1.id,
        category_id=cat1.id,
        name="Seekh Kebab",
        price=Decimal("199.50"),
        is_available=True,
    )
    noodles = MenuItem(
        restaurant_id=res2.id,
        category_id=cat2.id,
        name="Hakka Noodles",
        price=Decimal("180.00"),
        is_available=True,
    )
    db_session.add_all([biryani, kebab, noodles])
    await db_session.flush()

    # 5. Customers
    cust1 = Customer(whatsapp_customer_id="+919876543210", display_name="Rahul")
    cust2 = Customer(whatsapp_customer_id="+919876543211", display_name="Priya")
    db_session.add_all([cust1, cust2])
    await db_session.flush()

    # 6. Customer Sessions
    session1 = CustomerSession(
        customer_id=cust1.id,
        restaurant_id=res1.id,
        table_id=t1.id,
        status="ACTIVE",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=4),
    )
    session2 = CustomerSession(
        customer_id=cust2.id,
        restaurant_id=res2.id,
        table_id=t2.id,
        status="ACTIVE",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=4),
    )
    session_expired = CustomerSession(
        customer_id=cust1.id,
        restaurant_id=res1.id,
        table_id=t1.id,
        status="ACTIVE",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db_session.add_all([session1, session2, session_expired])
    await db_session.commit()

    return {
        "res1": res1,
        "res2": res2,
        "res_closed": res_closed,
        "t1": t1,
        "t2": t2,
        "biryani": biryani,
        "kebab": kebab,
        "noodles": noodles,
        "session1": session1,
        "session2": session2,
        "session_expired": session_expired,
    }


# ---------------------------------------------------------------------------
# Test 1: Checkout active cart creates Order in NEW status
# ---------------------------------------------------------------------------
async def test_1_checkout_active_cart_creates_order_in_new_status(
    async_client: AsyncClient, order_test_setup
):
    ctx = order_test_setup
    s1_id = str(ctx["session1"].id)
    b_id = str(ctx["biryani"].id)
    k_id = str(ctx["kebab"].id)

    # 1. Add items to cart: 2 Biryani (2 * 299 = 598), 1 Kebab (1 * 199.50 = 199.50)
    add_b = await async_client.post(
        "/api/v1/cart/items",
        json={"session_id": s1_id, "menu_item_id": b_id, "quantity": 2},
    )
    assert add_b.status_code == 200

    add_k = await async_client.post(
        "/api/v1/cart/items",
        json={"session_id": s1_id, "menu_item_id": k_id, "quantity": 1},
    )
    assert add_k.status_code == 200

    # 2. Checkout
    checkout_res = await async_client.post(
        "/api/v1/orders/checkout",
        json={
            "session_id": s1_id,
            "special_instructions": "Make it extra spicy, please!",
        },
    )
    assert checkout_res.status_code == 201
    data = checkout_res.json()

    assert data["status"] == "NEW"
    assert data["order_number"].startswith("ORD-")
    assert data["session_id"] == s1_id
    assert data["restaurant_id"] == str(ctx["res1"].id)
    assert data["table_id"] == str(ctx["t1"].id)
    assert data["table_number"] == "Table 1"
    assert data["special_instructions"] == "Make it extra spicy, please!"
    assert data["total_amount"] == "797.50"
    assert data["item_count"] == 3
    assert len(data["items"]) == 2

    # 3. Cart should now be empty for next round
    cart_res = await async_client.get(f"/api/v1/cart?session_id={s1_id}")
    assert cart_res.status_code == 200
    cart_data = cart_res.json()
    assert cart_data["item_count"] == 0
    assert len(cart_data["items"]) == 0


# ---------------------------------------------------------------------------
# Test 2: Checkout with empty cart returns 400 EMPTY_CART
# ---------------------------------------------------------------------------
async def test_2_checkout_empty_cart_fails(async_client: AsyncClient, order_test_setup):
    ctx = order_test_setup
    s1_id = str(ctx["session1"].id)

    checkout_res = await async_client.post(
        "/api/v1/orders/checkout",
        json={"session_id": s1_id},
    )
    assert checkout_res.status_code == 400
    err = checkout_res.json()
    assert err["error"]["code"] == "EMPTY_CART"


# ---------------------------------------------------------------------------
# Test 3: Checkout with expired session returns 400 SESSION_EXPIRED
# ---------------------------------------------------------------------------
async def test_3_checkout_expired_session_fails(
    async_client: AsyncClient, order_test_setup
):
    ctx = order_test_setup
    s_exp_id = str(ctx["session_expired"].id)

    checkout_res = await async_client.post(
        "/api/v1/orders/checkout",
        json={"session_id": s_exp_id},
    )
    assert checkout_res.status_code == 400
    assert checkout_res.json()["error"]["code"] == "SESSION_EXPIRED"


# ---------------------------------------------------------------------------
# Test 4: Price integrity - changing menu price does NOT change placed order
# ---------------------------------------------------------------------------
async def test_4_order_preserves_price_integrity_when_menu_price_changes(
    async_client: AsyncClient, db_session: AsyncSession, order_test_setup
):
    ctx = order_test_setup
    s1_id = str(ctx["session1"].id)
    b_id = str(ctx["biryani"].id)

    # 1. Add Biryani at 299.00
    await async_client.post(
        "/api/v1/cart/items",
        json={"session_id": s1_id, "menu_item_id": b_id, "quantity": 1},
    )

    # 2. Checkout
    checkout_res = await async_client.post(
        "/api/v1/orders/checkout",
        json={"session_id": s1_id},
    )
    assert checkout_res.status_code == 201
    order_data = checkout_res.json()
    order_id = order_data["id"]
    assert order_data["total_amount"] == "299.00"

    # 3. Mutate menu price in DB to 450.00
    biryani_db = await db_session.get(MenuItem, ctx["biryani"].id)
    biryani_db.price = Decimal("450.00")
    await db_session.commit()

    # 4. Fetch the order again
    get_res = await async_client.get(
        f"/api/v1/orders/{order_id}",
        headers={"X-Session-ID": s1_id},
    )
    assert get_res.status_code == 200
    refreshed_order = get_res.json()
    assert refreshed_order["total_amount"] == "299.00"
    assert refreshed_order["items"][0]["unit_price"] == "299.00"
    assert refreshed_order["items"][0]["line_total"] == "299.00"


# ---------------------------------------------------------------------------
# Test 5: Full kitchen lifecycle progression: NEW -> ACCEPTED -> PREPARING -> READY -> SERVED
# ---------------------------------------------------------------------------
async def test_5_full_kitchen_lifecycle_progression(
    async_client: AsyncClient, order_test_setup
):
    ctx = order_test_setup
    res1_id = str(ctx["res1"].id)
    s1_id = str(ctx["session1"].id)
    b_id = str(ctx["biryani"].id)

    # Place order
    await async_client.post(
        "/api/v1/cart/items",
        json={"session_id": s1_id, "menu_item_id": b_id, "quantity": 1},
    )
    order_res = await async_client.post(
        "/api/v1/orders/checkout",
        json={"session_id": s1_id},
    )
    order_id = order_res.json()["id"]
    assert order_res.json()["status"] == "NEW"

    # Step 1: NEW -> ACCEPTED
    res_step1 = await async_client.patch(
        f"/api/v1/kitchen/orders/{order_id}/status",
        json={"restaurant_id": res1_id, "status": "ACCEPTED"},
    )
    assert res_step1.status_code == 200
    assert res_step1.json()["status"] == "ACCEPTED"

    # Step 2: ACCEPTED -> PREPARING
    res_step2 = await async_client.patch(
        f"/api/v1/kitchen/orders/{order_id}/status",
        json={"restaurant_id": res1_id, "status": "PREPARING"},
    )
    assert res_step2.status_code == 200
    assert res_step2.json()["status"] == "PREPARING"

    # Step 3: PREPARING -> READY
    res_step3 = await async_client.patch(
        f"/api/v1/kitchen/orders/{order_id}/status",
        json={"restaurant_id": res1_id, "status": "READY"},
    )
    assert res_step3.status_code == 200
    assert res_step3.json()["status"] == "READY"

    # Step 4: READY -> SERVED
    res_step4 = await async_client.patch(
        f"/api/v1/kitchen/orders/{order_id}/status",
        json={"restaurant_id": res1_id, "status": "SERVED"},
    )
    assert res_step4.status_code == 200
    assert res_step4.json()["status"] == "SERVED"

    # Verify customer sees SERVED status
    cust_res = await async_client.get(
        f"/api/v1/orders/{order_id}?session_id={s1_id}"
    )
    assert cust_res.status_code == 200
    assert cust_res.json()["status"] == "SERVED"


# ---------------------------------------------------------------------------
# Test 6: Illegal status transitions are rejected with 400 INVALID_STATUS_TRANSITION
# ---------------------------------------------------------------------------
async def test_6_illegal_lifecycle_transitions_are_rejected(
    async_client: AsyncClient, order_test_setup
):
    ctx = order_test_setup
    res1_id = str(ctx["res1"].id)
    s1_id = str(ctx["session1"].id)
    b_id = str(ctx["biryani"].id)

    # Place order (status: NEW)
    await async_client.post(
        "/api/v1/cart/items",
        json={"session_id": s1_id, "menu_item_id": b_id, "quantity": 1},
    )
    order_res = await async_client.post(
        "/api/v1/orders/checkout",
        json={"session_id": s1_id},
    )
    order_id = order_res.json()["id"]

    # 1. Attempt NEW -> PREPARING (must be ACCEPTED first)
    bad1 = await async_client.patch(
        f"/api/v1/kitchen/orders/{order_id}/status",
        json={"restaurant_id": res1_id, "status": "PREPARING"},
    )
    assert bad1.status_code == 400
    assert bad1.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"

    # 2. Attempt NEW -> SERVED
    bad2 = await async_client.patch(
        f"/api/v1/kitchen/orders/{order_id}/status",
        json={"restaurant_id": res1_id, "status": "SERVED"},
    )
    assert bad2.status_code == 400
    assert bad2.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"

    # 3. Advance to ACCEPTED -> PREPARING
    await async_client.patch(
        f"/api/v1/kitchen/orders/{order_id}/status",
        json={"restaurant_id": res1_id, "status": "ACCEPTED"},
    )
    await async_client.patch(
        f"/api/v1/kitchen/orders/{order_id}/status",
        json={"restaurant_id": res1_id, "status": "PREPARING"},
    )

    # 4. Attempt PREPARING -> NEW (backward transition)
    bad3 = await async_client.patch(
        f"/api/v1/kitchen/orders/{order_id}/status",
        json={"restaurant_id": res1_id, "status": "NEW"},
    )
    assert bad3.status_code == 400
    assert bad3.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"

    # 5. Advance to READY -> SERVED
    await async_client.patch(
        f"/api/v1/kitchen/orders/{order_id}/status",
        json={"restaurant_id": res1_id, "status": "READY"},
    )
    await async_client.patch(
        f"/api/v1/kitchen/orders/{order_id}/status",
        json={"restaurant_id": res1_id, "status": "SERVED"},
    )

    # 6. Attempt SERVED -> READY (transitioning from terminal state)
    bad4 = await async_client.patch(
        f"/api/v1/kitchen/orders/{order_id}/status",
        json={"restaurant_id": res1_id, "status": "READY"},
    )
    assert bad4.status_code == 400
    assert bad4.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"


# ---------------------------------------------------------------------------
# Test 7: Cancellation rules
# ---------------------------------------------------------------------------
async def test_7_order_cancellation_rules(async_client: AsyncClient, order_test_setup):
    ctx = order_test_setup
    res1_id = str(ctx["res1"].id)
    s1_id = str(ctx["session1"].id)
    b_id = str(ctx["biryani"].id)

    # 1. Cancel from NEW
    await async_client.post(
        "/api/v1/cart/items",
        json={"session_id": s1_id, "menu_item_id": b_id, "quantity": 1},
    )
    order1 = (
        await async_client.post("/api/v1/orders/checkout", json={"session_id": s1_id})
    ).json()
    cancel_res = await async_client.patch(
        f"/api/v1/kitchen/orders/{order1['id']}/status",
        json={"restaurant_id": res1_id, "status": "CANCELLED"},
    )
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "CANCELLED"

    # 2. Cancel from ACCEPTED
    await async_client.post(
        "/api/v1/cart/items",
        json={"session_id": s1_id, "menu_item_id": b_id, "quantity": 1},
    )
    order2 = (
        await async_client.post("/api/v1/orders/checkout", json={"session_id": s1_id})
    ).json()
    await async_client.patch(
        f"/api/v1/kitchen/orders/{order2['id']}/status",
        json={"restaurant_id": res1_id, "status": "ACCEPTED"},
    )
    cancel_res2 = await async_client.patch(
        f"/api/v1/kitchen/orders/{order2['id']}/status",
        json={"restaurant_id": res1_id, "status": "CANCELLED"},
    )
    assert cancel_res2.status_code == 200
    assert cancel_res2.json()["status"] == "CANCELLED"

    # 3. Cannot cancel once PREPARING
    await async_client.post(
        "/api/v1/cart/items",
        json={"session_id": s1_id, "menu_item_id": b_id, "quantity": 1},
    )
    order3 = (
        await async_client.post("/api/v1/orders/checkout", json={"session_id": s1_id})
    ).json()
    await async_client.patch(
        f"/api/v1/kitchen/orders/{order3['id']}/status",
        json={"restaurant_id": res1_id, "status": "ACCEPTED"},
    )
    await async_client.patch(
        f"/api/v1/kitchen/orders/{order3['id']}/status",
        json={"restaurant_id": res1_id, "status": "PREPARING"},
    )
    bad_cancel = await async_client.patch(
        f"/api/v1/kitchen/orders/{order3['id']}/status",
        json={"restaurant_id": res1_id, "status": "CANCELLED"},
    )
    assert bad_cancel.status_code == 400
    assert bad_cancel.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"


# ---------------------------------------------------------------------------
# Test 8: Session isolation - customer cannot view another session's orders
# ---------------------------------------------------------------------------
async def test_8_customer_session_orders_isolation(
    async_client: AsyncClient, order_test_setup
):
    ctx = order_test_setup
    s1_id = str(ctx["session1"].id)
    s2_id = str(ctx["session2"].id)
    b_id = str(ctx["biryani"].id)
    n_id = str(ctx["noodles"].id)

    # Session 1 places order
    await async_client.post(
        "/api/v1/cart/items",
        json={"session_id": s1_id, "menu_item_id": b_id, "quantity": 1},
    )
    order1 = (
        await async_client.post("/api/v1/orders/checkout", json={"session_id": s1_id})
    ).json()

    # Session 2 places order
    await async_client.post(
        "/api/v1/cart/items",
        json={"session_id": s2_id, "menu_item_id": n_id, "quantity": 2},
    )
    order2 = (
        await async_client.post("/api/v1/orders/checkout", json={"session_id": s2_id})
    ).json()

    # Session 2 queries order list: must only see order2
    list_res = await async_client.get(f"/api/v1/orders?session_id={s2_id}")
    assert list_res.status_code == 200
    orders_s2 = list_res.json()
    assert len(orders_s2) == 1
    assert orders_s2[0]["id"] == order2["id"]

    # Session 2 attempts to view order1 directly: 404 ORDER_NOT_FOUND
    get_res = await async_client.get(
        f"/api/v1/orders/{order1['id']}?session_id={s2_id}"
    )
    assert get_res.status_code == 404
    assert get_res.json()["error"]["code"] == "ORDER_NOT_FOUND"


# ---------------------------------------------------------------------------
# Test 9: Kitchen tenant isolation
# ---------------------------------------------------------------------------
async def test_9_kitchen_tenant_isolation(async_client: AsyncClient, order_test_setup):
    ctx = order_test_setup
    res1_id = str(ctx["res1"].id)
    res2_id = str(ctx["res2"].id)
    s1_id = str(ctx["session1"].id)
    b_id = str(ctx["biryani"].id)

    # Session 1 at Restaurant 1 places order
    await async_client.post(
        "/api/v1/cart/items",
        json={"session_id": s1_id, "menu_item_id": b_id, "quantity": 1},
    )
    order1 = (
        await async_client.post("/api/v1/orders/checkout", json={"session_id": s1_id})
    ).json()

    # Restaurant 2 kitchen checks its queue: empty
    k2_queue = await async_client.get(
        f"/api/v1/kitchen/orders?restaurant_id={res2_id}"
    )
    assert k2_queue.status_code == 200
    assert len(k2_queue.json()) == 0

    # Restaurant 2 kitchen tries to advance Restaurant 1's order: 404
    bad_update = await async_client.patch(
        f"/api/v1/kitchen/orders/{order1['id']}/status",
        json={"restaurant_id": res2_id, "status": "ACCEPTED"},
    )
    assert bad_update.status_code == 404
    assert bad_update.json()["error"]["code"] == "ORDER_NOT_FOUND"


# ---------------------------------------------------------------------------
# Test 10: Privacy - customer WhatsApp identifier is NEVER in order responses
# ---------------------------------------------------------------------------
async def test_10_privacy_and_pii_protection(
    async_client: AsyncClient, order_test_setup
):
    ctx = order_test_setup
    res1_id = str(ctx["res1"].id)
    s1_id = str(ctx["session1"].id)
    b_id = str(ctx["biryani"].id)

    await async_client.post(
        "/api/v1/cart/items",
        json={"session_id": s1_id, "menu_item_id": b_id, "quantity": 1},
    )
    order = (
        await async_client.post("/api/v1/orders/checkout", json={"session_id": s1_id})
    ).json()

    # Check Customer OrderResponse
    assert "whatsapp_customer_id" not in order
    assert "customer_id" not in order
    assert "+919876543210" not in str(order)

    # Check KitchenOrderResponse
    k_res = await async_client.get(f"/api/v1/kitchen/orders?restaurant_id={res1_id}")
    k_orders = k_res.json()
    assert len(k_orders) == 1
    assert "whatsapp_customer_id" not in k_orders[0]
    assert "customer_id" not in k_orders[0]
    assert "+919876543210" not in str(k_orders[0])


# ---------------------------------------------------------------------------
# Test 11: Kitchen status filter
# ---------------------------------------------------------------------------
async def test_11_kitchen_status_filter(async_client: AsyncClient, order_test_setup):
    ctx = order_test_setup
    res1_id = str(ctx["res1"].id)
    s1_id = str(ctx["session1"].id)
    b_id = str(ctx["biryani"].id)

    # Order 1 (remains NEW)
    await async_client.post(
        "/api/v1/cart/items",
        json={"session_id": s1_id, "menu_item_id": b_id, "quantity": 1},
    )
    order1 = (
        await async_client.post("/api/v1/orders/checkout", json={"session_id": s1_id})
    ).json()

    # Order 2 (advance to PREPARING)
    await async_client.post(
        "/api/v1/cart/items",
        json={"session_id": s1_id, "menu_item_id": b_id, "quantity": 2},
    )
    order2 = (
        await async_client.post("/api/v1/orders/checkout", json={"session_id": s1_id})
    ).json()
    await async_client.patch(
        f"/api/v1/kitchen/orders/{order2['id']}/status",
        json={"restaurant_id": res1_id, "status": "ACCEPTED"},
    )
    await async_client.patch(
        f"/api/v1/kitchen/orders/{order2['id']}/status",
        json={"restaurant_id": res1_id, "status": "PREPARING"},
    )

    # Filter for PREPARING only
    prep_res = await async_client.get(
        f"/api/v1/kitchen/orders?restaurant_id={res1_id}&status=PREPARING"
    )
    assert prep_res.status_code == 200
    prep_orders = prep_res.json()
    assert len(prep_orders) == 1
    assert prep_orders[0]["id"] == order2["id"]

    # Filter for NEW only
    new_res = await async_client.get(
        f"/api/v1/kitchen/orders?restaurant_id={res1_id}&status=NEW"
    )
    assert new_res.status_code == 200
    new_orders = new_res.json()
    assert len(new_orders) == 1
    assert new_orders[0]["id"] == order1["id"]


# ---------------------------------------------------------------------------
# Test 12: Multiple order rounds in the same dining session
# ---------------------------------------------------------------------------
async def test_12_multiple_order_rounds_in_same_session(
    async_client: AsyncClient, order_test_setup
):
    ctx = order_test_setup
    s1_id = str(ctx["session1"].id)
    b_id = str(ctx["biryani"].id)
    k_id = str(ctx["kebab"].id)

    # Round 1: Starters (Kebab)
    await async_client.post(
        "/api/v1/cart/items",
        json={"session_id": s1_id, "menu_item_id": k_id, "quantity": 2},
    )
    round1 = (
        await async_client.post("/api/v1/orders/checkout", json={"session_id": s1_id})
    ).json()

    # Round 2: Mains (Biryani)
    await async_client.post(
        "/api/v1/cart/items",
        json={"session_id": s1_id, "menu_item_id": b_id, "quantity": 1},
    )
    round2 = (
        await async_client.post("/api/v1/orders/checkout", json={"session_id": s1_id})
    ).json()

    assert round1["id"] != round2["id"]
    assert round1["order_number"] != round2["order_number"]

    # Customer fetches session orders: sees both rounds
    orders_res = await async_client.get(f"/api/v1/orders?session_id={s1_id}")
    assert orders_res.status_code == 200
    session_orders = orders_res.json()
    assert len(session_orders) == 2
    order_ids = [o["id"] for o in session_orders]
    assert round1["id"] in order_ids
    assert round2["id"] in order_ids
