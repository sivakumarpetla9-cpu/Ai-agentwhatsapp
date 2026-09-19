import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.integrations.whatsapp.client import whatsapp_client
from app.models.bill import Bill, BillStatus
from app.models.cart import Cart, CartItem
from app.models.customer import Customer, CustomerSession
from app.models.menu import MenuCategory, MenuItem
from app.models.order import Order, OrderItem, OrderStatus
from app.models.restaurant import Restaurant, RestaurantTable
from app.services.billing import BillingService

settings = get_settings()


@pytest.fixture
async def billing_test_setup(db_session: AsyncSession):
    """
    Setup multi-restaurant fixtures for billing and settlement testing.
    Restaurant 1: SpiceBox
    Restaurant 2: DragonWok
    """
    whatsapp_client.clear_sent_messages()

    # 1. Restaurants
    res1 = Restaurant(name="SpiceBox Dine-In", is_active=True)
    res2 = Restaurant(name="DragonWok Dine-In", is_active=True)
    db_session.add_all([res1, res2])
    await db_session.flush()

    # 2. Tables
    t1 = RestaurantTable(restaurant_id=res1.id, table_number="Table 1", qr_token="qr-sp-t1")
    t2 = RestaurantTable(restaurant_id=res2.id, table_number="Table 2", qr_token="qr-dw-t2")
    db_session.add_all([t1, t2])
    await db_session.flush()

    # 3. Categories
    cat1 = MenuCategory(restaurant_id=res1.id, name="Biryani & Mains", display_order=1, is_active=True)
    cat2 = MenuCategory(restaurant_id=res2.id, name="Asian Noodles", display_order=1, is_active=True)
    db_session.add_all([cat1, cat2])
    await db_session.flush()

    # 4. Menu Items
    biryani = MenuItem(
        restaurant_id=res1.id,
        category_id=cat1.id,
        name="Chicken Dum Biryani",
        price=Decimal("280.00"),
        is_available=True,
    )
    coke = MenuItem(
        restaurant_id=res1.id,
        category_id=cat1.id,
        name="Coke",
        price=Decimal("40.00"),
        is_available=True,
    )
    gulab_jamun = MenuItem(
        restaurant_id=res1.id,
        category_id=cat1.id,
        name="Gulab Jamun",
        price=Decimal("90.00"),
        is_available=True,
    )
    lime = MenuItem(
        restaurant_id=res1.id,
        category_id=cat1.id,
        name="Fresh Lime",
        price=Decimal("60.00"),
        is_available=True,
    )
    noodles = MenuItem(
        restaurant_id=res2.id,
        category_id=cat2.id,
        name="Hakka Noodles",
        price=Decimal("180.00"),
        is_available=True,
    )
    db_session.add_all([biryani, coke, gulab_jamun, lime, noodles])
    await db_session.flush()

    # 5. Customers
    cust1 = Customer(whatsapp_customer_id="+919876543210", display_name="Rahul")
    cust2 = Customer(whatsapp_customer_id="+919876543211", display_name="Priya")
    db_session.add_all([cust1, cust2])
    await db_session.flush()

    # 6. Sessions
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
    db_session.add_all([session1, session2])
    await db_session.flush()

    # 7. Active Cart for session1
    cart1 = Cart(customer_session_id=session1.id, status="ACTIVE")
    db_session.add(cart1)
    await db_session.flush()

    await db_session.commit()

    return {
        "res1": res1,
        "res2": res2,
        "t1": t1,
        "t2": t2,
        "biryani": biryani,
        "coke": coke,
        "gulab_jamun": gulab_jamun,
        "lime": lime,
        "noodles": noodles,
        "cust1": cust1,
        "cust2": cust2,
        "session1": session1,
        "session2": session2,
        "cart1": cart1,
    }


def make_whatsapp_payload(
    from_phone: str,
    message_type: str = "text",
    text_body: str = "",
    button_id: str = "",
) -> Dict[str, Any]:
    """
    Construct inbound WhatsApp webhook payload.
    """
    msg_obj: Dict[str, Any] = {
        "from": from_phone,
        "id": "wamid.HBgLMTIzNDU2Nzg5MA==",
        "timestamp": "1726732800",
        "type": message_type,
    }
    if message_type == "text":
        msg_obj["text"] = {"body": text_body}
    elif message_type == "interactive":
        msg_obj["interactive"] = {
            "type": "button_reply",
            "button_reply": {"id": button_id, "title": "Button Title"},
        }

    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WHATSAPP_ENTRY_ID",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15551234567",
                                "phone_number_id": "100000000000001",
                            },
                            "contacts": [{"profile": {"name": "Customer"}, "wa_id": from_phone}],
                            "messages": [msg_obj],
                        },
                    }
                ],
            }
        ],
    }


@pytest.mark.asyncio
async def test_1_generate_bill_for_one_served_order(
    async_client: AsyncClient, db_session: AsyncSession, billing_test_setup
):
    """
    Scenario 1: Generate bill for one served order.
    """
    data = billing_test_setup
    s1 = data["session1"]
    res1 = data["res1"]
    t1 = data["t1"]
    biryani = data["biryani"]

    # Create SERVED order (Biryani x 2 = 560.00)
    order1 = Order(
        restaurant_id=res1.id,
        table_id=t1.id,
        customer_session_id=s1.id,
        status=OrderStatus.SERVED.value,
        total_amount=Decimal("560.00"),
    )
    db_session.add(order1)
    await db_session.flush()

    item1 = OrderItem(
        order_id=order1.id,
        menu_item_id=biryani.id,
        item_name=biryani.name,
        quantity=2,
        unit_price=Decimal("280.00"),
    )
    db_session.add(item1)
    await db_session.commit()

    # Generate bill
    res = await async_client.post(
        "/api/v1/billing/generate",
        json={"session_id": str(s1.id)},
    )
    assert res.status_code == 200
    b_data = res.json()
    assert b_data["bill_number"].startswith("BILL-")
    assert b_data["status"] == "OPEN"
    assert Decimal(str(b_data["subtotal"])) == Decimal("560.00")
    assert Decimal(str(b_data["grand_total"])) == Decimal("560.00")
    assert len(b_data["items"]) == 1
    assert b_data["items"][0]["item_name_snapshot"] == "Chicken Dum Biryani"
    assert b_data["items"][0]["quantity"] == 2
    assert Decimal(str(b_data["items"][0]["line_total"])) == Decimal("560.00")


@pytest.mark.asyncio
async def test_2_generate_bill_across_multiple_dining_rounds(
    async_client: AsyncClient, db_session: AsyncSession, billing_test_setup
):
    """
    Scenario 2: Generate bill across multiple dining rounds.
    Round 1: Biryani x 2 (560) + Coke x 2 (80) = 640
    Round 2: Gulab Jamun x 2 (180)
    Round 3: Fresh Lime x 1 (60)
    Total = 880
    """
    data = billing_test_setup
    s1 = data["session1"]
    res1 = data["res1"]
    t1 = data["t1"]
    biryani = data["biryani"]
    coke = data["coke"]
    gulab = data["gulab_jamun"]
    lime = data["lime"]

    # Round 1
    ord1 = Order(
        restaurant_id=res1.id, table_id=t1.id, customer_session_id=s1.id,
        status=OrderStatus.SERVED.value, total_amount=Decimal("640.00")
    )
    db_session.add(ord1)
    await db_session.flush()
    db_session.add(OrderItem(order_id=ord1.id, menu_item_id=biryani.id, item_name=biryani.name, quantity=2, unit_price=Decimal("280.00")))
    db_session.add(OrderItem(order_id=ord1.id, menu_item_id=coke.id, item_name=coke.name, quantity=2, unit_price=Decimal("40.00")))

    # Round 2
    ord2 = Order(
        restaurant_id=res1.id, table_id=t1.id, customer_session_id=s1.id,
        status=OrderStatus.SERVED.value, total_amount=Decimal("180.00")
    )
    db_session.add(ord2)
    await db_session.flush()
    db_session.add(OrderItem(order_id=ord2.id, menu_item_id=gulab.id, item_name=gulab.name, quantity=2, unit_price=Decimal("90.00")))

    # Round 3
    ord3 = Order(
        restaurant_id=res1.id, table_id=t1.id, customer_session_id=s1.id,
        status=OrderStatus.SERVED.value, total_amount=Decimal("60.00")
    )
    db_session.add(ord3)
    await db_session.flush()
    db_session.add(OrderItem(order_id=ord3.id, menu_item_id=lime.id, item_name=lime.name, quantity=1, unit_price=Decimal("60.00")))

    await db_session.commit()

    res = await async_client.post("/api/v1/billing/generate", json={"session_id": str(s1.id)})
    assert res.status_code == 200
    b_data = res.json()
    assert Decimal(str(b_data["subtotal"])) == Decimal("880.00")
    assert Decimal(str(b_data["grand_total"])) == Decimal("880.00")
    assert len(b_data["items"]) == 4
    assert len(b_data["orders_included"]) == 3


@pytest.mark.asyncio
async def test_3_cancelled_orders_excluded(
    async_client: AsyncClient, db_session: AsyncSession, billing_test_setup
):
    """
    Scenario 3: Cancelled orders excluded from bill.
    """
    data = billing_test_setup
    s1 = data["session1"]
    res1 = data["res1"]
    t1 = data["t1"]
    biryani = data["biryani"]
    coke = data["coke"]

    # Served order
    ord1 = Order(restaurant_id=res1.id, table_id=t1.id, customer_session_id=s1.id, status=OrderStatus.SERVED.value, total_amount=Decimal("280.00"))
    db_session.add(ord1)
    await db_session.flush()
    db_session.add(OrderItem(order_id=ord1.id, menu_item_id=biryani.id, item_name=biryani.name, quantity=1, unit_price=Decimal("280.00")))

    # Cancelled order
    ord2 = Order(restaurant_id=res1.id, table_id=t1.id, customer_session_id=s1.id, status=OrderStatus.CANCELLED.value, total_amount=Decimal("40.00"))
    db_session.add(ord2)
    await db_session.flush()
    db_session.add(OrderItem(order_id=ord2.id, menu_item_id=coke.id, item_name=coke.name, quantity=1, unit_price=Decimal("40.00")))

    await db_session.commit()

    res = await async_client.post("/api/v1/billing/generate", json={"session_id": str(s1.id)})
    assert res.status_code == 200
    b_data = res.json()
    assert Decimal(str(b_data["subtotal"])) == Decimal("280.00")
    assert len(b_data["items"]) == 1
    assert b_data["items"][0]["item_name_snapshot"] == "Chicken Dum Biryani"


@pytest.mark.asyncio
async def test_4_unresolved_orders_prevent_settlement(
    async_client: AsyncClient, db_session: AsyncSession, billing_test_setup
):
    """
    Scenario 4: Unresolved orders prevent settlement.
    """
    data = billing_test_setup
    s1 = data["session1"]
    res1 = data["res1"]
    t1 = data["t1"]
    biryani = data["biryani"]
    coke = data["coke"]

    # 1 SERVED order
    ord1 = Order(restaurant_id=res1.id, table_id=t1.id, customer_session_id=s1.id, status=OrderStatus.SERVED.value, total_amount=Decimal("280.00"))
    db_session.add(ord1)
    await db_session.flush()
    db_session.add(OrderItem(order_id=ord1.id, menu_item_id=biryani.id, item_name=biryani.name, quantity=1, unit_price=Decimal("280.00")))

    # 1 PREPARING order
    ord2 = Order(restaurant_id=res1.id, table_id=t1.id, customer_session_id=s1.id, status=OrderStatus.PREPARING.value, total_amount=Decimal("40.00"))
    db_session.add(ord2)
    await db_session.flush()
    db_session.add(OrderItem(order_id=ord2.id, menu_item_id=coke.id, item_name=coke.name, quantity=1, unit_price=Decimal("40.00")))

    await db_session.commit()

    # Bill can be generated
    res = await async_client.post("/api/v1/billing/generate", json={"session_id": str(s1.id)})
    assert res.status_code == 200
    bill_id = res.json()["id"]

    # Settlement must be rejected due to unresolved ord2
    settle_res = await async_client.post(f"/api/v1/billing/{bill_id}/settle")
    assert settle_res.status_code == 400
    err = settle_res.json()["error"]
    assert err["code"] == "UNRESOLVED_ORDERS"
    assert "Cannot settle table while there are unresolved orders" in err["message"]


@pytest.mark.asyncio
async def test_5_6_7_8_correct_totals_tax_and_decimal_precision(
    async_client: AsyncClient, db_session: AsyncSession, billing_test_setup, monkeypatch
):
    """
    Scenarios 5, 6, 7, 8: Subtotal, Tax calculation, Grand total, and Decimal precision.
    """
    data = billing_test_setup
    s1 = data["session1"]
    res1 = data["res1"]
    t1 = data["t1"]
    biryani = data["biryani"]

    # Configure 5% tax rate via settings
    monkeypatch.setattr(settings, "BILL_TAX_RATE", Decimal("0.05"))

    # Order 1: Biryani x 3 = 840.00
    ord1 = Order(restaurant_id=res1.id, table_id=t1.id, customer_session_id=s1.id, status=OrderStatus.SERVED.value, total_amount=Decimal("840.00"))
    db_session.add(ord1)
    await db_session.flush()
    db_session.add(OrderItem(order_id=ord1.id, menu_item_id=biryani.id, item_name=biryani.name, quantity=3, unit_price=Decimal("280.00")))
    await db_session.commit()

    res = await async_client.post("/api/v1/billing/generate", json={"session_id": str(s1.id)})
    assert res.status_code == 200
    b_data = res.json()

    subtotal = Decimal(str(b_data["subtotal"]))
    tax_amount = Decimal(str(b_data["tax_amount"]))
    grand_total = Decimal(str(b_data["grand_total"]))

    assert subtotal == Decimal("840.00")
    assert tax_amount == Decimal("42.00")  # 840 * 0.05 = 42.00
    assert grand_total == Decimal("882.00")


@pytest.mark.asyncio
async def test_9_bill_item_snapshots_preserved_when_menu_changes(
    async_client: AsyncClient, db_session: AsyncSession, billing_test_setup
):
    """
    Scenario 9: Bill item snapshots are preserved even if menu item price/name changes later.
    """
    data = billing_test_setup
    s1 = data["session1"]
    res1 = data["res1"]
    t1 = data["t1"]
    biryani = data["biryani"]

    ord1 = Order(restaurant_id=res1.id, table_id=t1.id, customer_session_id=s1.id, status=OrderStatus.SERVED.value, total_amount=Decimal("280.00"))
    db_session.add(ord1)
    await db_session.flush()
    db_session.add(OrderItem(order_id=ord1.id, menu_item_id=biryani.id, item_name=biryani.name, quantity=1, unit_price=Decimal("280.00")))
    await db_session.commit()

    # Generate bill
    gen_res = await async_client.post("/api/v1/billing/generate", json={"session_id": str(s1.id)})
    assert gen_res.status_code == 200

    # Alter MenuItem in database
    biryani.name = "Super Royal Biryani"
    biryani.price = Decimal("999.00")
    await db_session.commit()

    # Retrieve bill
    get_res = await async_client.get(f"/api/v1/billing?session_id={s1.id}")
    assert get_res.status_code == 200
    b_data = get_res.json()
    assert b_data["items"][0]["item_name_snapshot"] == "Chicken Dum Biryani"
    assert Decimal(str(b_data["items"][0]["unit_price"])) == Decimal("280.00")
    assert Decimal(str(b_data["subtotal"])) == Decimal("280.00")


@pytest.mark.asyncio
async def test_10_repeated_bill_request_is_idempotent(
    async_client: AsyncClient, db_session: AsyncSession, billing_test_setup
):
    """
    Scenario 10: Repeated bill request is idempotent and returns the same bill without duplicates.
    """
    data = billing_test_setup
    s1 = data["session1"]
    res1 = data["res1"]
    t1 = data["t1"]
    biryani = data["biryani"]

    ord1 = Order(restaurant_id=res1.id, table_id=t1.id, customer_session_id=s1.id, status=OrderStatus.SERVED.value, total_amount=Decimal("280.00"))
    db_session.add(ord1)
    await db_session.flush()
    db_session.add(OrderItem(order_id=ord1.id, menu_item_id=biryani.id, item_name=biryani.name, quantity=1, unit_price=Decimal("280.00")))
    await db_session.commit()

    # Call 1
    res1 = await async_client.post("/api/v1/billing/generate", json={"session_id": str(s1.id)})
    assert res1.status_code == 200
    bill1 = res1.json()

    # Call 2
    res2 = await async_client.post("/api/v1/billing/generate", json={"session_id": str(s1.id)})
    assert res2.status_code == 200
    bill2 = res2.json()

    assert bill1["id"] == bill2["id"]
    assert bill1["bill_number"] == bill2["bill_number"]
    assert len(bill1["items"]) == len(bill2["items"]) == 1


@pytest.mark.asyncio
async def test_11_duplicate_concurrent_bill_requests_integrity(
    db_session: AsyncSession, billing_test_setup
):
    """
    Scenario 11: Database constraint prevents duplicate OPEN bills for same session.
    """
    data = billing_test_setup
    s1 = data["session1"]
    res1 = data["res1"]
    t1 = data["t1"]

    b1 = Bill(
        restaurant_id=res1.id,
        table_id=t1.id,
        session_id=s1.id,
        subtotal=Decimal("100.00"),
        grand_total=Decimal("100.00"),
        status=BillStatus.OPEN.value,
    )
    db_session.add(b1)
    await db_session.commit()

    # Attempting to insert another OPEN bill for same session must violate unique constraint
    b2 = Bill(
        restaurant_id=res1.id,
        table_id=t1.id,
        session_id=s1.id,
        subtotal=Decimal("200.00"),
        grand_total=Decimal("200.00"),
        status=BillStatus.OPEN.value,
    )
    db_session.add(b2)
    with pytest.raises(Exception):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_12_13_14_settlement_closes_session_archives_cart_frees_table(
    async_client: AsyncClient, db_session: AsyncSession, billing_test_setup
):
    """
    Scenarios 12, 13, 14:
    - Settlement closes session (status CLOSED).
    - Settlement archives active cart (status ARCHIVED).
    - Table becomes reusable for new customers.
    """
    data = billing_test_setup
    s1 = data["session1"]
    res1 = data["res1"]
    t1 = data["t1"]
    biryani = data["biryani"]

    ord1 = Order(restaurant_id=res1.id, table_id=t1.id, customer_session_id=s1.id, status=OrderStatus.SERVED.value, total_amount=Decimal("280.00"))
    db_session.add(ord1)
    await db_session.flush()
    db_session.add(OrderItem(order_id=ord1.id, menu_item_id=biryani.id, item_name=biryani.name, quantity=1, unit_price=Decimal("280.00")))
    await db_session.commit()

    gen_res = await async_client.post("/api/v1/billing/generate", json={"session_id": str(s1.id)})
    assert gen_res.status_code == 200
    bill_id = gen_res.json()["id"]

    # Settle
    settle_res = await async_client.post(f"/api/v1/billing/{bill_id}/settle")
    assert settle_res.status_code == 200
    assert settle_res.json()["status"] == "SETTLED"
    assert settle_res.json()["settled_at"] is not None

    # Check session is CLOSED
    db_sess = await db_session.get(CustomerSession, s1.id)
    assert db_sess.status == "CLOSED"
    assert db_sess.is_currently_active is False

    # Check cart is ARCHIVED
    db_cart = await db_session.get(Cart, data["cart1"].id)
    assert db_cart.status == "ARCHIVED"

    # Verify table is reusable: new customer can start a session at table 1
    new_cust = Customer(whatsapp_customer_id="+919999988888", display_name="Vikram")
    db_session.add(new_cust)
    await db_session.flush()

    new_session = CustomerSession(
        customer_id=new_cust.id,
        restaurant_id=res1.id,
        table_id=t1.id,
        status="ACTIVE",
    )
    db_session.add(new_session)
    await db_session.commit()
    assert new_session.is_currently_active is True


@pytest.mark.asyncio
async def test_15_historical_orders_remain_intact(
    async_client: AsyncClient, db_session: AsyncSession, billing_test_setup
):
    """
    Scenario 15: Historical orders remain queryable and intact after settlement.
    """
    data = billing_test_setup
    s1 = data["session1"]
    res1 = data["res1"]
    t1 = data["t1"]
    biryani = data["biryani"]

    ord1 = Order(restaurant_id=res1.id, table_id=t1.id, customer_session_id=s1.id, status=OrderStatus.SERVED.value, total_amount=Decimal("280.00"))
    db_session.add(ord1)
    await db_session.flush()
    db_session.add(OrderItem(order_id=ord1.id, menu_item_id=biryani.id, item_name=biryani.name, quantity=1, unit_price=Decimal("280.00")))
    await db_session.commit()

    gen_res = await async_client.post("/api/v1/billing/generate", json={"session_id": str(s1.id)})
    bill_id = gen_res.json()["id"]

    await async_client.post(f"/api/v1/billing/{bill_id}/settle")

    # Order still exists in database
    ord_check = await db_session.get(Order, ord1.id)
    assert ord_check is not None
    assert ord_check.status == OrderStatus.SERVED.value
    assert len(ord_check.items) == 1


@pytest.mark.asyncio
async def test_16_settled_bill_cannot_be_settled_twice(
    async_client: AsyncClient, db_session: AsyncSession, billing_test_setup
):
    """
    Scenario 16: Settled bill cannot be settled twice.
    """
    data = billing_test_setup
    s1 = data["session1"]
    res1 = data["res1"]
    t1 = data["t1"]
    biryani = data["biryani"]

    ord1 = Order(restaurant_id=res1.id, table_id=t1.id, customer_session_id=s1.id, status=OrderStatus.SERVED.value, total_amount=Decimal("280.00"))
    db_session.add(ord1)
    await db_session.flush()
    db_session.add(OrderItem(order_id=ord1.id, menu_item_id=biryani.id, item_name=biryani.name, quantity=1, unit_price=Decimal("280.00")))
    await db_session.commit()

    gen_res = await async_client.post("/api/v1/billing/generate", json={"session_id": str(s1.id)})
    bill_id = gen_res.json()["id"]

    # First settlement
    settle1 = await async_client.post(f"/api/v1/billing/{bill_id}/settle")
    assert settle1.status_code == 200

    # Second settlement attempt
    settle2 = await async_client.post(f"/api/v1/billing/{bill_id}/settle")
    assert settle2.status_code == 400
    assert settle2.json()["error"]["code"] == "BILL_ALREADY_SETTLED"


@pytest.mark.asyncio
async def test_17_cross_restaurant_bill_access_rejected(
    async_client: AsyncClient, db_session: AsyncSession, billing_test_setup
):
    """
    Scenario 17: Cross-restaurant bill access is strictly rejected.
    """
    data = billing_test_setup
    s1 = data["session1"]
    res1 = data["res1"]
    res2 = data["res2"]
    t1 = data["t1"]
    biryani = data["biryani"]

    ord1 = Order(restaurant_id=res1.id, table_id=t1.id, customer_session_id=s1.id, status=OrderStatus.SERVED.value, total_amount=Decimal("280.00"))
    db_session.add(ord1)
    await db_session.flush()
    db_session.add(OrderItem(order_id=ord1.id, menu_item_id=biryani.id, item_name=biryani.name, quantity=1, unit_price=Decimal("280.00")))
    await db_session.commit()

    gen_res = await async_client.post("/api/v1/billing/generate", json={"session_id": str(s1.id)})
    bill_id = gen_res.json()["id"]

    # Settle with wrong restaurant_id
    res = await async_client.post(
        f"/api/v1/billing/{bill_id}/settle",
        json={"restaurant_id": str(res2.id)},
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "BILL_NOT_FOUND"


@pytest.mark.asyncio
async def test_18_cross_session_bill_access_rejected(
    async_client: AsyncClient, db_session: AsyncSession, billing_test_setup
):
    """
    Scenario 18: Cross-session bill access is strictly rejected.
    """
    data = billing_test_setup
    s1 = data["session1"]
    s2 = data["session2"]
    res1 = data["res1"]
    t1 = data["t1"]
    biryani = data["biryani"]

    ord1 = Order(restaurant_id=res1.id, table_id=t1.id, customer_session_id=s1.id, status=OrderStatus.SERVED.value, total_amount=Decimal("280.00"))
    db_session.add(ord1)
    await db_session.flush()
    db_session.add(OrderItem(order_id=ord1.id, menu_item_id=biryani.id, item_name=biryani.name, quantity=1, unit_price=Decimal("280.00")))
    await db_session.commit()

    gen_res = await async_client.post("/api/v1/billing/generate", json={"session_id": str(s1.id)})
    bill_id = gen_res.json()["id"]

    # Settle with wrong session_id
    res = await async_client.post(
        f"/api/v1/billing/{bill_id}/settle",
        json={"session_id": str(s2.id)},
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "BILL_NOT_FOUND"


@pytest.mark.asyncio
async def test_19_whatsapp_bill_command_works(
    async_client: AsyncClient, db_session: AsyncSession, billing_test_setup
):
    """
    Scenario 19: WhatsApp BILL command generates bill and outputs formatted receipt.
    """
    data = billing_test_setup
    s1 = data["session1"]
    res1 = data["res1"]
    t1 = data["t1"]
    biryani = data["biryani"]
    coke = data["coke"]

    # 1 SERVED order
    ord1 = Order(restaurant_id=res1.id, table_id=t1.id, customer_session_id=s1.id, status=OrderStatus.SERVED.value, total_amount=Decimal("320.00"))
    db_session.add(ord1)
    await db_session.flush()
    db_session.add(OrderItem(order_id=ord1.id, menu_item_id=biryani.id, item_name=biryani.name, quantity=1, unit_price=Decimal("280.00")))
    db_session.add(OrderItem(order_id=ord1.id, menu_item_id=coke.id, item_name=coke.name, quantity=1, unit_price=Decimal("40.00")))
    await db_session.commit()

    # Customer texts "BILL"
    payload = make_whatsapp_payload(from_phone="+919876543210", text_body="BILL")
    res = await async_client.post("/api/v1/integrations/whatsapp/webhook", json=payload)
    assert res.status_code == 200

    assert len(whatsapp_client.sent_messages) == 1
    msg = whatsapp_client.sent_messages[-1]
    assert msg.to == "+919876543210"
    assert "Table: Table 1" in msg.body
    assert "Bill: BILL-" in msg.body
    assert "Chicken Dum Biryani × 1    ₹280.00" in msg.body
    assert "Coke × 1    ₹40.00" in msg.body
    assert "Subtotal: ₹320.00" in msg.body
    assert "Total: ₹320.00" in msg.body


@pytest.mark.asyncio
async def test_20_whatsapp_bill_does_not_expose_customer_phone_number(
    async_client: AsyncClient, db_session: AsyncSession, billing_test_setup
):
    """
    Scenario 20: WhatsApp BILL message never leaks customer phone number in text body.
    """
    data = billing_test_setup
    s1 = data["session1"]
    res1 = data["res1"]
    t1 = data["t1"]
    biryani = data["biryani"]

    ord1 = Order(restaurant_id=res1.id, table_id=t1.id, customer_session_id=s1.id, status=OrderStatus.SERVED.value, total_amount=Decimal("280.00"))
    db_session.add(ord1)
    await db_session.flush()
    db_session.add(OrderItem(order_id=ord1.id, menu_item_id=biryani.id, item_name=biryani.name, quantity=1, unit_price=Decimal("280.00")))
    await db_session.commit()

    payload = make_whatsapp_payload(from_phone="+919876543210", button_id="REQUEST_BILL", message_type="interactive")
    res = await async_client.post("/api/v1/integrations/whatsapp/webhook", json=payload)
    assert res.status_code == 200

    msg = whatsapp_client.sent_messages[-1]
    assert "+919876543210" not in msg.body
    assert "9876543210" not in msg.body


@pytest.mark.asyncio
async def test_21_missing_active_session_handled_safely(
    async_client: AsyncClient, db_session: AsyncSession, billing_test_setup
):
    """
    Scenario 21: Customer with no active session texts "BILL" safely.
    """
    payload = make_whatsapp_payload(from_phone="+919111122222", text_body="bill")
    res = await async_client.post("/api/v1/integrations/whatsapp/webhook", json=payload)
    assert res.status_code == 200

    sent_texts = [m.body or "" for m in whatsapp_client.sent_messages]
    assert any("You do not have an active dining session" in t for t in sent_texts)


@pytest.mark.asyncio
async def test_22_no_bill_created_when_there_are_no_billable_orders(
    async_client: AsyncClient, db_session: AsyncSession, billing_test_setup
):
    """
    Scenario 22: No bill created when there are no billable orders.
    """
    data = billing_test_setup
    s1 = data["session1"]

    # Session has 0 orders
    res = await async_client.post("/api/v1/billing/generate", json={"session_id": str(s1.id)})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "NO_BILLABLE_ORDERS"

    # On WhatsApp: friendly message
    payload = make_whatsapp_payload(from_phone="+919876543210", text_body="BILL")
    wa_res = await async_client.post("/api/v1/integrations/whatsapp/webhook", json=payload)
    assert wa_res.status_code == 200
    assert "No served orders found yet" in whatsapp_client.sent_messages[-1].body


@pytest.mark.asyncio
async def test_23_get_session_bill_endpoint(
    async_client: AsyncClient, db_session: AsyncSession, billing_test_setup
):
    """
    Scenario 23: GET /api/v1/billing?session_id=... returns current bill.
    """
    data = billing_test_setup
    s1 = data["session1"]
    res1 = data["res1"]
    t1 = data["t1"]
    biryani = data["biryani"]

    ord1 = Order(restaurant_id=res1.id, table_id=t1.id, customer_session_id=s1.id, status=OrderStatus.SERVED.value, total_amount=Decimal("280.00"))
    db_session.add(ord1)
    await db_session.flush()
    db_session.add(OrderItem(order_id=ord1.id, menu_item_id=biryani.id, item_name=biryani.name, quantity=1, unit_price=Decimal("280.00")))
    await db_session.commit()

    # Generate bill
    await async_client.post("/api/v1/billing/generate", json={"session_id": str(s1.id)})

    # Fetch
    res = await async_client.get(f"/api/v1/billing?session_id={s1.id}")
    assert res.status_code == 200
    b_data = res.json()
    assert b_data["status"] == "OPEN"
    assert Decimal(str(b_data["subtotal"])) == Decimal("280.00")
