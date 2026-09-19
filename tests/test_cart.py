import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cart import Cart, CartItem
from app.models.customer import Customer, CustomerSession
from app.models.menu import MenuCategory, MenuItem
from app.models.restaurant import Restaurant, RestaurantTable


@pytest.fixture
async def cart_test_setup(db_session: AsyncSession):
    """
    Setup multi-restaurant fixtures for menu and cart testing.
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
    t1 = RestaurantTable(restaurant_id=res1.id, table_number="Table 1", qr_token="qr-sp-1")
    t2 = RestaurantTable(restaurant_id=res2.id, table_number="Table 1", qr_token="qr-dw-1")
    t_closed = RestaurantTable(restaurant_id=res_closed.id, table_number="Table 1", qr_token="qr-nk-1")
    db_session.add_all([t1, t2, t_closed])
    await db_session.flush()

    # 3. Categories for Restaurant 1
    cat1_active = MenuCategory(restaurant_id=res1.id, name="Biryani", display_order=1, is_active=True)
    cat1_inactive = MenuCategory(restaurant_id=res1.id, name="Seasonal Specials", display_order=2, is_active=False)
    # Categories for Restaurant 2
    cat2_active = MenuCategory(restaurant_id=res2.id, name="Noodles", display_order=1, is_active=True)
    db_session.add_all([cat1_active, cat1_inactive, cat2_active])
    await db_session.flush()

    # 4. Menu Items for Restaurant 1
    item_chicken_biryani = MenuItem(
        restaurant_id=res1.id,
        category_id=cat1_active.id,
        name="Chicken Biryani",
        price=Decimal("280.00"),
        is_available=True,
        display_order=1,
    )
    item_mutton_biryani = MenuItem(
        restaurant_id=res1.id,
        category_id=cat1_active.id,
        name="Mutton Biryani",
        price=Decimal("360.00"),
        is_available=True,
        display_order=2,
    )
    item_sold_out = MenuItem(
        restaurant_id=res1.id,
        category_id=cat1_active.id,
        name="Special Haleem",
        price=Decimal("250.00"),
        is_available=False,  # Unavailable
        display_order=3,
    )
    item_in_inactive_cat = MenuItem(
        restaurant_id=res1.id,
        category_id=cat1_inactive.id,
        name="Winter Soup",
        price=Decimal("150.00"),
        is_available=True,
        display_order=1,
    )

    # Menu Items for Restaurant 2
    item_hakka_noodles = MenuItem(
        restaurant_id=res2.id,
        category_id=cat2_active.id,
        name="Hakka Noodles",
        price=Decimal("210.00"),
        is_available=True,
        display_order=1,
    )

    db_session.add_all([
        item_chicken_biryani,
        item_mutton_biryani,
        item_sold_out,
        item_in_inactive_cat,
        item_hakka_noodles,
    ])
    await db_session.flush()

    # 5. Customers & Sessions
    cust1 = Customer(whatsapp_customer_id="+919876540001", display_name="Alice")
    cust2 = Customer(whatsapp_customer_id="+919876540002", display_name="Bob")
    db_session.add_all([cust1, cust2])
    await db_session.flush()

    # Alice's active session at Restaurant 1
    session_alice = CustomerSession(
        customer_id=cust1.id,
        restaurant_id=res1.id,
        table_id=t1.id,
        status="ACTIVE",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=4),
    )
    # Bob's active session at Restaurant 2
    session_bob = CustomerSession(
        customer_id=cust2.id,
        restaurant_id=res2.id,
        table_id=t2.id,
        status="ACTIVE",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=4),
    )
    # Expired session
    session_expired = CustomerSession(
        customer_id=cust1.id,
        restaurant_id=res1.id,
        table_id=t1.id,
        status="ACTIVE",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    # Session in closed restaurant
    session_closed_res = CustomerSession(
        customer_id=cust2.id,
        restaurant_id=res_closed.id,
        table_id=t_closed.id,
        status="ACTIVE",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=4),
    )

    db_session.add_all([session_alice, session_bob, session_expired, session_closed_res])
    await db_session.commit()

    return {
        "res1": res1,
        "res2": res2,
        "cat1_active": cat1_active,
        "cat1_inactive": cat1_inactive,
        "item_chicken_biryani": item_chicken_biryani,
        "item_mutton_biryani": item_mutton_biryani,
        "item_sold_out": item_sold_out,
        "item_in_inactive_cat": item_in_inactive_cat,
        "item_hakka_noodles": item_hakka_noodles,
        "session_alice": session_alice,
        "session_bob": session_bob,
        "session_expired": session_expired,
        "session_closed_res": session_closed_res,
    }


@pytest.mark.asyncio
async def test_1_active_session_can_access_its_restaurant_menu(
    async_client: AsyncClient, cart_test_setup: dict
) -> None:
    """1. Test that active session can access its restaurant menu."""
    s_alice = cart_test_setup["session_alice"]
    response = await async_client.get("/api/v1/menu", headers={"X-Session-ID": str(s_alice.id)})
    assert response.status_code == 200
    data = response.json()
    assert data["restaurant_id"] == str(s_alice.restaurant_id)
    category_names = [c["name"] for c in data["categories"]]
    assert "Biryani" in category_names


@pytest.mark.asyncio
async def test_2_expired_session_cannot_access_menu(
    async_client: AsyncClient, cart_test_setup: dict
) -> None:
    """2. Test that an expired session cannot access the menu."""
    s_expired = cart_test_setup["session_expired"]
    response = await async_client.get("/api/v1/menu", headers={"X-Session-ID": str(s_expired.id)})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SESSION_EXPIRED"


@pytest.mark.asyncio
async def test_3_inactive_restaurant_cannot_provide_menu(
    async_client: AsyncClient, cart_test_setup: dict
) -> None:
    """3. Test that an inactive restaurant cannot provide a menu."""
    s_closed = cart_test_setup["session_closed_res"]
    response = await async_client.get("/api/v1/menu", headers={"X-Session-ID": str(s_closed.id)})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "RESTAURANT_INACTIVE"


@pytest.mark.asyncio
async def test_4_inactive_category_is_not_returned(
    async_client: AsyncClient, cart_test_setup: dict
) -> None:
    """4. Test that inactive categories are not returned."""
    s_alice = cart_test_setup["session_alice"]
    response = await async_client.get("/api/v1/menu", headers={"X-Session-ID": str(s_alice.id)})
    assert response.status_code == 200
    category_names = [c["name"] for c in response.json()["categories"]]
    assert "Seasonal Specials" not in category_names


@pytest.mark.asyncio
async def test_5_unavailable_menu_item_is_not_selectable(
    async_client: AsyncClient, cart_test_setup: dict
) -> None:
    """5. Test that unavailable menu items are omitted from menu and cannot be added."""
    s_alice = cart_test_setup["session_alice"]

    # 1. Check menu response
    response = await async_client.get("/api/v1/menu", headers={"X-Session-ID": str(s_alice.id)})
    assert response.status_code == 200
    all_items = [item["name"] for cat in response.json()["categories"] for item in cat["items"]]
    assert "Special Haleem" not in all_items

    # 2. Check attempting to add to cart
    add_payload = {
        "menu_item_id": str(cart_test_setup["item_sold_out"].id),
        "quantity": 1,
    }
    add_res = await async_client.post(
        "/api/v1/cart/items",
        json=add_payload,
        headers={"X-Session-ID": str(s_alice.id)},
    )
    assert add_res.status_code == 400
    assert add_res.json()["error"]["code"] == "ITEM_UNAVAILABLE"


@pytest.mark.asyncio
async def test_6_customer_can_create_and_use_active_cart(
    async_client: AsyncClient, cart_test_setup: dict
) -> None:
    """6. Test that a customer can view their active cart."""
    s_alice = cart_test_setup["session_alice"]
    response = await async_client.get("/api/v1/cart", headers={"X-Session-ID": str(s_alice.id)})
    assert response.status_code == 200
    cart_data = response.json()
    assert cart_data["session_id"] == str(s_alice.id)
    assert cart_data["items"] == []
    assert Decimal(str(cart_data["subtotal"])) == Decimal("0.00")
    assert cart_data["item_count"] == 0


@pytest.mark.asyncio
async def test_7_customer_can_add_available_item(
    async_client: AsyncClient, cart_test_setup: dict
) -> None:
    """7. Test adding an available menu item to the cart."""
    s_alice = cart_test_setup["session_alice"]
    item = cart_test_setup["item_chicken_biryani"]

    payload = {"menu_item_id": str(item.id), "quantity": 2}
    response = await async_client.post(
        "/api/v1/cart/items",
        json=payload,
        headers={"X-Session-ID": str(s_alice.id)},
    )
    assert response.status_code == 200
    cart = response.json()
    assert len(cart["items"]) == 1
    assert cart["items"][0]["name"] == "Chicken Biryani"
    assert cart["items"][0]["quantity"] == 2
    assert Decimal(str(cart["items"][0]["unit_price"])) == Decimal("280.00")
    assert Decimal(str(cart["items"][0]["line_total"])) == Decimal("560.00")
    assert Decimal(str(cart["subtotal"])) == Decimal("560.00")
    assert cart["item_count"] == 2


@pytest.mark.asyncio
async def test_8_adding_same_item_twice_increases_quantity(
    async_client: AsyncClient, cart_test_setup: dict
) -> None:
    """8. Test that adding the same item twice increases quantity (no duplicates)."""
    s_alice = cart_test_setup["session_alice"]
    item = cart_test_setup["item_chicken_biryani"]

    payload = {"menu_item_id": str(item.id), "quantity": 2}
    await async_client.post("/api/v1/cart/items", json=payload, headers={"X-Session-ID": str(s_alice.id)})

    # Add 1 more of the same item
    payload2 = {"menu_item_id": str(item.id), "quantity": 1}
    res = await async_client.post("/api/v1/cart/items", json=payload2, headers={"X-Session-ID": str(s_alice.id)})
    assert res.status_code == 200
    cart = res.json()

    assert len(cart["items"]) == 1
    assert cart["items"][0]["quantity"] == 3
    assert Decimal(str(cart["items"][0]["line_total"])) == Decimal("840.00")
    assert Decimal(str(cart["subtotal"])) == Decimal("840.00")
    assert cart["item_count"] == 3


@pytest.mark.asyncio
async def test_9_quantity_must_be_greater_than_zero(
    async_client: AsyncClient, cart_test_setup: dict
) -> None:
    """9. Test that quantity <= 0 is rejected."""
    s_alice = cart_test_setup["session_alice"]
    item = cart_test_setup["item_chicken_biryani"]

    # 1. In add endpoint
    payload = {"menu_item_id": str(item.id), "quantity": 0}
    res = await async_client.post("/api/v1/cart/items", json=payload, headers={"X-Session-ID": str(s_alice.id)})
    assert res.status_code == 422  # Pydantic validation error ge=1


@pytest.mark.asyncio
async def test_10_and_11_price_snapshotting_and_historical_integrity(
    async_client: AsyncClient, db_session: AsyncSession, cart_test_setup: dict
) -> None:
    """10 & 11. Test that CartItem snapshots price and subsequent MenuItem price changes do not affect it."""
    s_alice = cart_test_setup["session_alice"]
    item = cart_test_setup["item_chicken_biryani"]

    # Add item when price is 280.00
    payload = {"menu_item_id": str(item.id), "quantity": 2}
    res = await async_client.post("/api/v1/cart/items", json=payload, headers={"X-Session-ID": str(s_alice.id)})
    assert res.status_code == 200
    assert Decimal(str(res.json()["items"][0]["unit_price"])) == Decimal("280.00")

    # Now simulate a restaurant price change: Chicken Biryani increases to 320.00
    stmt = select(MenuItem).where(MenuItem.id == item.id)
    db_item = (await db_session.execute(stmt)).scalars().first()
    db_item.price = Decimal("320.00")
    await db_session.commit()

    # Re-fetch customer cart: existing unit_price must still be 280.00!
    cart_res = await async_client.get("/api/v1/cart", headers={"X-Session-ID": str(s_alice.id)})
    assert cart_res.status_code == 200
    cart = cart_res.json()
    assert Decimal(str(cart["items"][0]["unit_price"])) == Decimal("280.00")
    assert Decimal(str(cart["items"][0]["line_total"])) == Decimal("560.00")
    assert Decimal(str(cart["subtotal"])) == Decimal("560.00")


@pytest.mark.asyncio
async def test_12_customer_cannot_add_item_from_another_restaurant(
    async_client: AsyncClient, cart_test_setup: dict
) -> None:
    """12. Test cross-restaurant item addition is rejected."""
    s_alice = cart_test_setup["session_alice"]  # SpiceBox
    dragon_wok_item = cart_test_setup["item_hakka_noodles"]  # DragonWok

    payload = {"menu_item_id": str(dragon_wok_item.id), "quantity": 1}
    res = await async_client.post("/api/v1/cart/items", json=payload, headers={"X-Session-ID": str(s_alice.id)})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "CROSS_RESTAURANT_ITEM_REJECTED"


@pytest.mark.asyncio
async def test_13_customer_cannot_read_another_restaurant_menu(
    async_client: AsyncClient, cart_test_setup: dict
) -> None:
    """13. Test that customer can only read their session's restaurant menu."""
    s_alice = cart_test_setup["session_alice"]  # SpiceBox
    res = await async_client.get("/api/v1/menu", headers={"X-Session-ID": str(s_alice.id)})
    assert res.status_code == 200
    data = res.json()
    # Ensure DragonWok noodles are nowhere in Alice's menu
    item_names = [i["name"] for c in data["categories"] for i in c["items"]]
    assert "Hakka Noodles" not in item_names


@pytest.mark.asyncio
async def test_14_customer_cannot_modify_another_sessions_cart(
    async_client: AsyncClient, cart_test_setup: dict
) -> None:
    """14. Test that a customer cannot modify another session's cart items."""
    s_alice = cart_test_setup["session_alice"]
    s_bob = cart_test_setup["session_bob"]

    # Alice adds item to her cart
    item = cart_test_setup["item_chicken_biryani"]
    res = await async_client.post(
        "/api/v1/cart/items",
        json={"menu_item_id": str(item.id), "quantity": 1},
        headers={"X-Session-ID": str(s_alice.id)},
    )
    alice_item_id = res.json()["items"][0]["id"]

    # Bob attempts to modify Alice's cart item
    bob_patch = await async_client.patch(
        f"/api/v1/cart/items/{alice_item_id}",
        json={"quantity": 5},
        headers={"X-Session-ID": str(s_bob.id)},
    )
    assert bob_patch.status_code == 404
    assert bob_patch.json()["error"]["code"] == "CART_ITEM_NOT_FOUND"


@pytest.mark.asyncio
async def test_15_customer_can_update_quantity(
    async_client: AsyncClient, cart_test_setup: dict
) -> None:
    """15. Test updating quantity of an existing cart item."""
    s_alice = cart_test_setup["session_alice"]
    item = cart_test_setup["item_chicken_biryani"]

    add_res = await async_client.post(
        "/api/v1/cart/items",
        json={"menu_item_id": str(item.id), "quantity": 1},
        headers={"X-Session-ID": str(s_alice.id)},
    )
    cart_item_id = add_res.json()["items"][0]["id"]

    # Update to 4
    patch_res = await async_client.patch(
        f"/api/v1/cart/items/{cart_item_id}",
        json={"quantity": 4},
        headers={"X-Session-ID": str(s_alice.id)},
    )
    assert patch_res.status_code == 200
    cart = patch_res.json()
    assert cart["items"][0]["quantity"] == 4
    assert Decimal(str(cart["items"][0]["line_total"])) == Decimal("1120.00")
    assert Decimal(str(cart["subtotal"])) == Decimal("1120.00")


@pytest.mark.asyncio
async def test_16_customer_can_remove_cart_item(
    async_client: AsyncClient, cart_test_setup: dict
) -> None:
    """16. Test removing a specific cart item."""
    s_alice = cart_test_setup["session_alice"]
    item1 = cart_test_setup["item_chicken_biryani"]
    item2 = cart_test_setup["item_mutton_biryani"]

    await async_client.post("/api/v1/cart/items", json={"menu_item_id": str(item1.id), "quantity": 1}, headers={"X-Session-ID": str(s_alice.id)})
    res2 = await async_client.post("/api/v1/cart/items", json={"menu_item_id": str(item2.id), "quantity": 2}, headers={"X-Session-ID": str(s_alice.id)})
    cart = res2.json()
    assert len(cart["items"]) == 2

    item_to_remove = cart["items"][0]["id"]
    del_res = await async_client.delete(f"/api/v1/cart/items/{item_to_remove}", headers={"X-Session-ID": str(s_alice.id)})
    assert del_res.status_code == 200
    cart_after = del_res.json()
    assert len(cart_after["items"]) == 1
    assert cart_after["items"][0]["name"] == "Mutton Biryani"


@pytest.mark.asyncio
async def test_17_customer_can_clear_the_cart(
    async_client: AsyncClient, cart_test_setup: dict
) -> None:
    """17. Test clearing all items from the active cart."""
    s_alice = cart_test_setup["session_alice"]
    item = cart_test_setup["item_chicken_biryani"]

    await async_client.post("/api/v1/cart/items", json={"menu_item_id": str(item.id), "quantity": 3}, headers={"X-Session-ID": str(s_alice.id)})

    clear_res = await async_client.post("/api/v1/cart/clear", headers={"X-Session-ID": str(s_alice.id)})
    assert clear_res.status_code == 200
    cart = clear_res.json()
    assert cart["items"] == []
    assert Decimal(str(cart["subtotal"])) == Decimal("0.00")
    assert cart["item_count"] == 0


@pytest.mark.asyncio
async def test_18_and_19_server_calculates_subtotal_with_decimal_precision(
    async_client: AsyncClient, cart_test_setup: dict
) -> None:
    """18 & 19. Test exact Decimal precision and subtotal calculations across multiple items."""
    s_alice = cart_test_setup["session_alice"]
    item1 = cart_test_setup["item_chicken_biryani"]  # 280.00
    item2 = cart_test_setup["item_mutton_biryani"]   # 360.00

    # Add 3 Chicken Biryanis (3 * 280 = 840)
    await async_client.post("/api/v1/cart/items", json={"menu_item_id": str(item1.id), "quantity": 3}, headers={"X-Session-ID": str(s_alice.id)})
    # Add 2 Mutton Biryanis (2 * 360 = 720)
    res = await async_client.post("/api/v1/cart/items", json={"menu_item_id": str(item2.id), "quantity": 2}, headers={"X-Session-ID": str(s_alice.id)})

    cart = res.json()
    assert Decimal(str(cart["subtotal"])) == Decimal("1560.00")
    assert cart["item_count"] == 5
    # Verify exact string representation of decimals
    assert cart["subtotal"] == "1560.00" or float(cart["subtotal"]) == 1560.0
