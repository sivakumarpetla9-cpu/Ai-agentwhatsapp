import re
import uuid
from decimal import Decimal
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.whatsapp.client import whatsapp_client
from app.models.customer import Customer, CustomerSession
from app.models.menu import MenuCategory, MenuItem
from app.models.order import Order, OrderStatus
from app.models.restaurant import Restaurant, RestaurantTable
from scripts.simulate_chat import WhatsAppSimulator


@pytest.fixture
async def simulator_setup(db_session: AsyncSession):
    """
    Setup multi-restaurant and menu fixtures for testing the CLI simulator.
    """
    whatsapp_client.clear_sent_messages()

    # 1. Restaurants
    res1 = Restaurant(name="SpiceBox", is_active=True)
    res2 = Restaurant(name="DragonWok", is_active=True)
    db_session.add_all([res1, res2])
    await db_session.flush()

    # 2. Tables
    t1 = RestaurantTable(restaurant_id=res1.id, table_number="Table 1", qr_token="qr-sp-t1", is_active=True)
    t2 = RestaurantTable(restaurant_id=res1.id, table_number="Table 2", qr_token="qr-sp-t2", is_active=True)
    t3 = RestaurantTable(restaurant_id=res1.id, table_number="Table 3", qr_token="qr-sp-t3", is_active=True)
    t_dw = RestaurantTable(restaurant_id=res2.id, table_number="Table 1", qr_token="qr-dw-t1", is_active=True)
    db_session.add_all([t1, t2, t3, t_dw])
    await db_session.flush()

    # 3. Categories
    cat_biryani = MenuCategory(restaurant_id=res1.id, name="Biryani", display_order=1, is_active=True)
    cat_drinks = MenuCategory(restaurant_id=res1.id, name="Beverages", display_order=2, is_active=True)
    db_session.add_all([cat_biryani, cat_drinks])
    await db_session.flush()

    # 4. Items
    b_chicken = MenuItem(
        restaurant_id=res1.id,
        category_id=cat_biryani.id,
        name="Chicken Biryani",
        price=Decimal("280.00"),
        is_available=True,
    )
    b_veg = MenuItem(
        restaurant_id=res1.id,
        category_id=cat_biryani.id,
        name="Veg Biryani",
        price=Decimal("220.00"),
        is_available=True,
    )
    coke = MenuItem(
        restaurant_id=res1.id,
        category_id=cat_drinks.id,
        name="Coke",
        price=Decimal("40.00"),
        is_available=True,
    )
    db_session.add_all([b_chicken, b_veg, coke])
    await db_session.commit()

    return {
        "res1": res1,
        "res2": res2,
        "t1": t1,
        "t2": t2,
        "t3": t3,
        "b_chicken": b_chicken,
        "b_veg": b_veg,
        "coke": coke,
    }


# ---------------------------------------------------------------------------
# Test 1 & 2: Simulator Startup & Restaurant Selection
# ---------------------------------------------------------------------------
async def test_1_and_2_simulator_startup_and_restaurant_selection(
    db_session: AsyncSession, simulator_setup
):
    ctx = simulator_setup
    sim = WhatsAppSimulator(db_session, customer_phone="+919876543210")

    # 1. Startup
    banner = await sim.initialize()
    assert "WhatsApp Restaurant Ordering Simulator" in banner
    assert "SpiceBox" in banner
    assert "+9******10" in banner  # Customer identity masked

    # 2. Restaurant Listing & Selection
    res_list = await sim.list_restaurants()
    assert "SpiceBox" in res_list
    assert "DragonWok" in res_list

    switch_msg = await sim.select_restaurant("DragonWok")
    assert "Switched to restaurant: DragonWok" in switch_msg
    assert sim.restaurant.name == "DragonWok"

    # Switch back to SpiceBox
    await sim.select_restaurant("SpiceBox")
    assert sim.restaurant.name == "SpiceBox"


# ---------------------------------------------------------------------------
# Test 3: QR Table Flow
# ---------------------------------------------------------------------------
async def test_3_qr_table_flow(db_session: AsyncSession, simulator_setup):
    ctx = simulator_setup
    sim = WhatsAppSimulator(db_session, customer_phone="+919876543210")
    await sim.initialize()

    # List tables
    qr_list = await sim.handle_command("qr")
    assert "Available demo QR tables:" in qr_list
    assert "Table 1" in qr_list
    assert "Table 2" in qr_list

    # Select Table 3
    resp = await sim.handle_command("qr 3")
    assert "QR detected." in resp
    assert "Table 3" in resp
    assert "Session created." in resp
    assert sim.current_session_id is not None

    # Verify session in DB
    sess = await db_session.get(CustomerSession, sim.current_session_id)
    assert sess.status == "ACTIVE"
    assert sess.table.table_number == "Table 3"


# ---------------------------------------------------------------------------
# Test 4: Direct Table Flow
# ---------------------------------------------------------------------------
async def test_4_direct_table_flow(db_session: AsyncSession, simulator_setup):
    ctx = simulator_setup
    sim = WhatsAppSimulator(db_session, customer_phone="+919876543211")
    await sim.initialize()

    # List tables
    tables_list = await sim.handle_command("tables")
    assert "Please select your table:" in tables_list
    assert "[1] Table 1" in tables_list

    # Select Table 2
    resp = await sim.handle_command("tables 2")
    assert "Table selected." in resp
    assert "Table 2" in resp
    assert "Session created." in resp
    assert sim.current_session_id is not None


# ---------------------------------------------------------------------------
# Test 5 & 6: Menu & Category Browsing
# ---------------------------------------------------------------------------
async def test_5_and_6_menu_and_category_browsing(db_session: AsyncSession, simulator_setup):
    ctx = simulator_setup
    sim = WhatsAppSimulator(db_session)
    await sim.initialize()
    await sim.handle_command("qr 1")

    # 5. Menu categories
    menu_resp = await sim.handle_command("menu")
    assert "SpiceBox Menu" in menu_resp
    assert "1. Biryani" in menu_resp
    assert "2. Beverages" in menu_resp

    # 6. Category 1 items
    cat_resp = await sim.handle_command("category 1")
    assert "Biryani" in cat_resp
    assert "Chicken Biryani — ₹280.00" in cat_resp
    assert "Veg Biryani — ₹220.00" in cat_resp


# ---------------------------------------------------------------------------
# Test 7, 8, 9, 10: Cart Operations (Add, Qty, Remove, Clear, Display)
# ---------------------------------------------------------------------------
async def test_7_to_10_cart_operations(db_session: AsyncSession, simulator_setup):
    ctx = simulator_setup
    sim = WhatsAppSimulator(db_session)
    await sim.initialize()
    await sim.handle_command("qr 1")
    await sim.handle_command("category 1")

    # 7. Add item 1 (Chicken Biryani)
    add_resp = await sim.handle_command("add 1 2")
    assert "Chicken Biryani added to cart." in add_resp
    assert "Quantity: 2" in add_resp

    # Add item 2 (Veg Biryani)
    await sim.handle_command("add 2 1")

    # 10. View Cart
    cart_resp = await sim.handle_command("cart")
    assert "YOUR CART" in cart_resp
    assert "Chicken Biryani × 2    ₹560.00" in cart_resp
    assert "Veg Biryani × 1    ₹220.00" in cart_resp
    assert "Subtotal: ₹780.00" in cart_resp

    # 8. Update Quantity (Chicken Biryani to 3)
    qty_resp = await sim.handle_command("qty 1 3")
    assert "Chicken Biryani × 3    ₹840.00" in qty_resp
    assert "Subtotal: ₹1060.00" in qty_resp

    # 9. Remove item 2 (Veg Biryani)
    rem_resp = await sim.handle_command("remove 2")
    assert "Item removed from cart." in rem_resp
    assert "Veg Biryani" not in rem_resp
    assert "Subtotal: ₹840.00" in rem_resp

    # Clear Cart
    clear_resp = await sim.handle_command("clear")
    assert "Your cart has been cleared." in clear_resp


# ---------------------------------------------------------------------------
# Test 11 & 12: Checkout & Multi-Round Dining
# ---------------------------------------------------------------------------
async def test_11_and_12_checkout_and_multi_round_dining(db_session: AsyncSession, simulator_setup):
    ctx = simulator_setup
    sim = WhatsAppSimulator(db_session)
    await sim.initialize()
    await sim.handle_command("qr 3")
    initial_session_id = sim.current_session_id

    # Round 1: Chicken Biryani x 2
    await sim.handle_command("category 1")
    await sim.handle_command("add 1 2")
    checkout1 = await sim.handle_command("confirm")
    assert "Order created successfully." in checkout1
    assert "Total: ₹560.00" in checkout1
    assert "Table 3" in checkout1

    # Verify session remains same
    assert sim.current_session_id == initial_session_id

    # Round 2: Beverages -> Coke x 2
    await sim.handle_command("category 2")
    await sim.handle_command("add 1 2")
    checkout2 = await sim.handle_command("confirm")
    assert "Order created successfully." in checkout2
    assert "Total: ₹80.00" in checkout2

    # Check orders
    orders_resp = await sim.handle_command("orders")
    assert "Your orders:" in orders_resp
    # Should list both orders in NEW state
    assert "NEW" in orders_resp


# ---------------------------------------------------------------------------
# Test 13 to 17: Kitchen Lifecycle & WhatsApp Live Notifications
# ---------------------------------------------------------------------------
async def test_13_to_17_kitchen_lifecycle_and_notifications(
    db_session: AsyncSession, simulator_setup
):
    ctx = simulator_setup
    sim = WhatsAppSimulator(db_session)
    await sim.initialize()
    await sim.handle_command("qr 1")
    await sim.handle_command("category 1")
    await sim.handle_command("add 1 1")
    await sim.handle_command("confirm")

    # Get placed order number
    orders_resp = await sim.handle_command("orders")
    match = re.search(r"ORD-[A-F0-9]+", orders_resp)
    assert match is not None
    ord_num = match.group(0)

    whatsapp_client.clear_sent_messages()
    sim.last_sent_count = 0

    # 13. Kitchen ACCEPT
    acc_resp = await sim.handle_command(f"kitchen accept {ord_num}")
    assert "Kitchen status updated:\nACCEPTED" in acc_resp
    assert "OUTBOUND WHATSAPP" in acc_resp
    assert "Your order has been accepted by the restaurant." in acc_resp

    # 14. Kitchen PREPARING
    prep_resp = await sim.handle_command(f"kitchen preparing {ord_num}")
    assert "Kitchen status updated:\nPREPARING" in prep_resp
    assert "Your order is now being prepared." in prep_resp

    # 15. Kitchen READY
    rdy_resp = await sim.handle_command(f"kitchen ready {ord_num}")
    assert "Kitchen status updated:\nREADY" in rdy_resp
    assert "Your order is ready." in rdy_resp

    # 16. Kitchen SERVED
    srv_resp = await sim.handle_command(f"kitchen served {ord_num}")
    assert "Kitchen status updated:\nSERVED" in srv_resp
    assert "Your order has been served." in srv_resp

    # 17. Verify outbound messages in mock client
    assert len(whatsapp_client.sent_messages) == 4


# ---------------------------------------------------------------------------
# Test 18: Notification Idempotency
# ---------------------------------------------------------------------------
async def test_18_duplicate_kitchen_notification_protected(
    db_session: AsyncSession, simulator_setup
):
    ctx = simulator_setup
    sim = WhatsAppSimulator(db_session)
    await sim.initialize()
    await sim.handle_command("qr 1")
    await sim.handle_command("category 1")
    await sim.handle_command("add 1 1")
    await sim.handle_command("confirm")

    orders_resp = await sim.handle_command("orders")
    match = re.search(r"ORD-[A-F0-9]+", orders_resp)
    assert match is not None
    ord_num = match.group(0)

    # Move to ACCEPTED
    await sim.handle_command(f"kitchen accept {ord_num}")
    count_after_first = len(whatsapp_client.sent_messages)

    # Calling notification service again for same status should be a no-op
    target_order = (
        await db_session.execute(select(Order).where(Order.order_number == ord_num))
    ).scalars().first()
    await sim.notification_service.send_kitchen_status_notification(
        restaurant_id=sim.restaurant.id,
        order_id=target_order.id,
        new_status="ACCEPTED",
    )
    assert len(whatsapp_client.sent_messages) == count_after_first


# ---------------------------------------------------------------------------
# Test 19 to 24: Bill Generation & Settlement Rules
# ---------------------------------------------------------------------------
async def test_19_to_24_bill_generation_and_settlement(
    db_session: AsyncSession, simulator_setup
):
    ctx = simulator_setup
    sim = WhatsAppSimulator(db_session)
    await sim.initialize()
    await sim.handle_command("qr 3")
    sess_id = sim.current_session_id

    # Place order
    await sim.handle_command("category 1")
    await sim.handle_command("add 1 2")  # 280 x 2 = 560
    await sim.handle_command("confirm")

    orders_resp = await sim.handle_command("orders")
    match = re.search(r"ORD-[A-F0-9]+", orders_resp)
    assert match is not None
    ord_num = match.group(0)

    # 21. Attempt settlement with unresolved order in NEW
    settle_unresolved = await sim.handle_command("settle")
    assert "unresolved" in settle_unresolved.lower() or "no billable orders" in settle_unresolved.lower()

    # Advance order: NEW -> ACCEPTED -> PREPARING -> READY -> SERVED
    for st in ["accept", "preparing", "ready", "served"]:
        await sim.handle_command(f"kitchen {st} {ord_num}")

    # 19. Bill Command
    bill_resp = await sim.handle_command("bill")
    assert "BILL" in bill_resp
    assert "Table 3" in bill_resp
    assert "Chicken Biryani × 2    ₹560.00" in bill_resp
    assert "Total: ₹560.00" in bill_resp

    # Verify session is STILL active
    refreshed_sess = await db_session.get(CustomerSession, sess_id)
    assert refreshed_sess.status == "ACTIVE"

    # 20. Settle Command
    settle_resp = await sim.handle_command("settle")
    assert "settled." in settle_resp
    assert "Session closed." in settle_resp
    assert "Table 3 is now available." in settle_resp

    # 22. Session is CLOSED
    refreshed_sess2 = await db_session.get(CustomerSession, sess_id)
    assert refreshed_sess2.status == "CLOSED"

    # 24. Historical order remains intact
    ord_entity = (
        await db_session.execute(select(Order).where(Order.order_number == ord_num))
    ).scalars().first()
    assert ord_entity is not None
    assert ord_entity.status == "SERVED"
    assert ord_entity.total_amount == Decimal("560.00")


# ---------------------------------------------------------------------------
# Test 25: Customer WhatsApp Identity Never Exposed
# ---------------------------------------------------------------------------
async def test_25_customer_identity_never_exposed(
    db_session: AsyncSession, simulator_setup
):
    ctx = simulator_setup
    raw_phone = "+919876543219"
    sim = WhatsAppSimulator(db_session, customer_phone=raw_phone)
    init_msg = await sim.initialize()
    assert raw_phone not in init_msg

    await sim.handle_command("qr 1")
    sess_info = await sim.handle_command("session")
    assert raw_phone not in sess_info
    assert "whatsapp" not in sess_info.lower()


# ---------------------------------------------------------------------------
# Test 26: Full End-to-End Multi-Round Dining Integration Scenario
# ---------------------------------------------------------------------------
async def test_26_end_to_end_dining_scenario(
    db_session: AsyncSession, simulator_setup
):
    """
    START -> Select SpiceBox -> QR Table 3 -> View Menu -> Add Biryani x 2 -> View Cart ->
    Checkout -> Kitchen Accept -> Preparing -> Ready -> Served -> Outbound Notifications ->
    Add Coke x 2 -> Checkout Round 2 -> Kitchen Lifecycle -> Bill -> Settle -> Table Freed.
    """
    ctx = simulator_setup
    sim = WhatsAppSimulator(db_session, customer_phone="+919876543200")

    # 1. Startup & Restaurant
    await sim.initialize()
    assert sim.restaurant.name == "SpiceBox"

    # 2. QR Table 3
    qr_res = await sim.handle_command("qr 3")
    assert "Table: Table 3" in qr_res
    session_id = sim.current_session_id

    # 3. View Menu
    menu_res = await sim.handle_command("menu")
    assert "Categories:" in menu_res

    # 4. Add Chicken Biryani x 2
    await sim.handle_command("category 1")
    add_res = await sim.handle_command("add 1 2")
    assert "Chicken Biryani added to cart." in add_res

    # 5. View Cart
    cart_res = await sim.handle_command("cart")
    assert "Subtotal: ₹560.00" in cart_res

    # 6. Checkout Round 1
    chk1_res = await sim.handle_command("confirm")
    assert "Order created successfully." in chk1_res
    assert "Total: ₹560.00" in chk1_res

    # Get Order 1 ID
    orders_1 = await sim.handle_command("orders")
    ord1_num = re.search(r"ORD-[A-F0-9]+", orders_1).group(0)

    # 7. Kitchen advances Order 1: ACCEPTED -> PREPARING -> READY -> SERVED
    for st in ["accept", "preparing", "ready", "served"]:
        k_res = await sim.handle_command(f"kitchen {st} {ord1_num}")
        assert "OUTBOUND WHATSAPP" in k_res

    # 8. Round 2: Add Coke x 2
    await sim.handle_command("category 2")
    await sim.handle_command("add 1 2")
    chk2_res = await sim.handle_command("confirm")
    assert "Total: ₹80.00" in chk2_res

    # Get Order 2 ID
    orders_2 = await sim.handle_command("orders")
    all_orders = re.findall(r"ORD-[A-F0-9]+", orders_2)
    ord2_num = [o for o in all_orders if o != ord1_num][0]

    # 9. Kitchen advances Order 2 to SERVED
    for st in ["accept", "preparing", "ready", "served"]:
        await sim.handle_command(f"kitchen {st} {ord2_num}")

    # 10. Customer requests Bill
    bill_res = await sim.handle_command("bill")
    assert "Chicken Biryani × 2    ₹560.00" in bill_res
    assert "Coke × 2    ₹80.00" in bill_res
    assert "Total: ₹640.00" in bill_res

    # 11. Settlement
    settle_res = await sim.handle_command("settle")
    assert "settled." in settle_res
    assert "Session closed." in settle_res
    assert "Table 3 is now available." in settle_res

    # 12. Confirm session closed in database
    db_sess = await db_session.get(CustomerSession, session_id)
    assert db_sess.status == "CLOSED"
