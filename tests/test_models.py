import uuid
from decimal import Decimal
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.menu import MenuCategory, MenuItem
from app.models.restaurant import Restaurant, RestaurantTable, generate_qr_token


@pytest.mark.asyncio
async def test_restaurant_can_be_created(db_session: AsyncSession) -> None:
    """1. Test that a restaurant can be created."""
    restaurant = Restaurant(
        name="Tandoor Treats",
        description="Authentic tandoor kitchen",
        phone_number="+919123456780",
        address="10 Main St",
        is_active=True,
    )
    db_session.add(restaurant)
    await db_session.commit()

    assert restaurant.id is not None
    assert restaurant.name == "Tandoor Treats"
    assert restaurant.is_active is True
    assert restaurant.created_at is not None
    assert restaurant.updated_at is not None


@pytest.mark.asyncio
async def test_tables_belong_to_correct_restaurant(db_session: AsyncSession) -> None:
    """2. Test that tables belong to the correct restaurant."""
    restaurant = Restaurant(name="Curry Palace")
    db_session.add(restaurant)
    await db_session.flush()

    table1 = RestaurantTable(
        restaurant_id=restaurant.id,
        table_number="Table 1",
        qr_token=generate_qr_token(),
    )
    table2 = RestaurantTable(
        restaurant_id=restaurant.id,
        table_number="Table 2",
        qr_token=generate_qr_token(),
    )
    db_session.add_all([table1, table2])
    await db_session.commit()

    # Query via relationship
    stmt = select(Restaurant).where(Restaurant.id == restaurant.id)
    result = await db_session.execute(stmt)
    res_fetched = result.scalars().first()
    assert res_fetched is not None
    assert len(res_fetched.tables) == 2
    assert {t.table_number for t in res_fetched.tables} == {"Table 1", "Table 2"}


@pytest.mark.asyncio
async def test_duplicate_table_numbers_rejected_in_same_restaurant(
    db_session: AsyncSession,
) -> None:
    """3. Test that duplicate table numbers are rejected within the same restaurant."""
    restaurant = Restaurant(name="Biryani Hub")
    db_session.add(restaurant)
    await db_session.flush()

    table1 = RestaurantTable(
        restaurant_id=restaurant.id,
        table_number="Table 1",
        qr_token=generate_qr_token(),
    )
    db_session.add(table1)
    await db_session.flush()

    # Second table with identical table_number in same restaurant
    table2 = RestaurantTable(
        restaurant_id=restaurant.id,
        table_number="Table 1",
        qr_token=generate_qr_token(),
    )
    db_session.add(table2)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_same_table_number_can_exist_in_different_restaurants(
    db_session: AsyncSession,
) -> None:
    """4. Test that the same table number can exist in different restaurants."""
    restaurant_a = Restaurant(name="Restaurant A")
    restaurant_b = Restaurant(name="Restaurant B")
    db_session.add_all([restaurant_a, restaurant_b])
    await db_session.flush()

    table_a = RestaurantTable(
        restaurant_id=restaurant_a.id,
        table_number="Table 1",
        qr_token=generate_qr_token(),
    )
    table_b = RestaurantTable(
        restaurant_id=restaurant_b.id,
        table_number="Table 1",
        qr_token=generate_qr_token(),
    )
    db_session.add_all([table_a, table_b])
    await db_session.commit()

    assert table_a.id is not None
    assert table_b.id is not None
    assert table_a.table_number == table_b.table_number
    assert table_a.restaurant_id != table_b.restaurant_id


@pytest.mark.asyncio
async def test_qr_tokens_are_unique(db_session: AsyncSession) -> None:
    """5. Test that QR tokens are globally unique."""
    restaurant = Restaurant(name="Cafe Delight")
    db_session.add(restaurant)
    await db_session.flush()

    shared_token = "unique-test-token-12345"
    table1 = RestaurantTable(
        restaurant_id=restaurant.id,
        table_number="Table 1",
        qr_token=shared_token,
    )
    db_session.add(table1)
    await db_session.flush()

    table2 = RestaurantTable(
        restaurant_id=restaurant.id,
        table_number="Table 2",
        qr_token=shared_token,
    )
    db_session.add(table2)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_categories_belong_to_restaurants(db_session: AsyncSession) -> None:
    """6. Test that categories belong to restaurants."""
    restaurant = Restaurant(name="Grill House")
    db_session.add(restaurant)
    await db_session.flush()

    cat = MenuCategory(
        restaurant_id=restaurant.id,
        name="Starters",
        display_order=1,
    )
    db_session.add(cat)
    await db_session.commit()

    assert cat.id is not None
    assert cat.restaurant_id == restaurant.id
    assert cat.restaurant.name == "Grill House"


@pytest.mark.asyncio
async def test_menu_items_belong_to_categories(db_session: AsyncSession) -> None:
    """7. Test that menu items belong to categories."""
    restaurant = Restaurant(name="Dosa Corner")
    db_session.add(restaurant)
    await db_session.flush()

    cat = MenuCategory(restaurant_id=restaurant.id, name="South Indian")
    db_session.add(cat)
    await db_session.flush()

    item = MenuItem(
        restaurant_id=restaurant.id,
        category_id=cat.id,
        name="Masala Dosa",
        price=Decimal("120.00"),
    )
    db_session.add(item)
    await db_session.commit()

    assert item.id is not None
    assert item.category_id == cat.id

    # Query category with select to verify async relationship loading
    stmt = select(MenuCategory).where(MenuCategory.id == cat.id)
    cat_fetched = (await db_session.execute(stmt)).scalars().first()
    assert cat_fetched is not None
    assert len(cat_fetched.items) == 1
    assert cat_fetched.items[0].name == "Masala Dosa"


@pytest.mark.asyncio
async def test_negative_menu_prices_are_rejected(db_session: AsyncSession) -> None:
    """8. Test that negative menu prices are rejected by CheckConstraint."""
    restaurant = Restaurant(name="Budget Bites")
    db_session.add(restaurant)
    await db_session.flush()

    cat = MenuCategory(restaurant_id=restaurant.id, name="Snacks")
    db_session.add(cat)
    await db_session.flush()

    item = MenuItem(
        restaurant_id=restaurant.id,
        category_id=cat.id,
        name="Samosa",
        price=Decimal("-10.00"),
    )
    db_session.add(item)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_menu_items_cannot_reference_category_from_another_restaurant(
    db_session: AsyncSession,
) -> None:
    """9. Test that menu items cannot reference a category from another restaurant."""
    restaurant_a = Restaurant(name="Restaurant Alpha")
    restaurant_b = Restaurant(name="Restaurant Beta")
    db_session.add_all([restaurant_a, restaurant_b])
    await db_session.flush()

    cat_b = MenuCategory(restaurant_id=restaurant_b.id, name="Beta Beverages")
    db_session.add(cat_b)
    await db_session.flush()

    # Attempt to create menu item in Restaurant A referencing Category from Restaurant B
    illegal_item = MenuItem(
        restaurant_id=restaurant_a.id,
        category_id=cat_b.id,  # Owned by Restaurant B!
        name="Iced Tea",
        price=Decimal("50.00"),
    )
    db_session.add(illegal_item)
    with pytest.raises(IntegrityError):
        await db_session.flush()
