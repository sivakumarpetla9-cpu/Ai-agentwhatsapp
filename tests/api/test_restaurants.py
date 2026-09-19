import uuid
from decimal import Decimal
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.menu import MenuCategory, MenuItem
from app.models.restaurant import Restaurant, RestaurantTable, generate_qr_token


@pytest.fixture
async def sample_restaurant_data(db_session: AsyncSession) -> Restaurant:
    """
    Populate a sample restaurant with tables, categories, and items for API testing.
    """
    restaurant = Restaurant(
        name="Royal Spice",
        description="Fine dining restaurant",
        phone_number="+919876543210",
        address="100 Royal Road",
        is_active=True,
    )
    db_session.add(restaurant)
    await db_session.flush()

    # Tables
    table1 = RestaurantTable(
        restaurant_id=restaurant.id,
        table_number="Table 1",
        qr_token=generate_qr_token(),
        is_active=True,
    )
    table2 = RestaurantTable(
        restaurant_id=restaurant.id,
        table_number="Table 2",
        qr_token=generate_qr_token(),
        is_active=True,
    )
    db_session.add_all([table1, table2])

    # Categories
    cat_starters = MenuCategory(
        restaurant_id=restaurant.id,
        name="Starters",
        display_order=1,
        is_active=True,
    )
    cat_mains = MenuCategory(
        restaurant_id=restaurant.id,
        name="Main Course",
        display_order=2,
        is_active=True,
    )
    db_session.add_all([cat_starters, cat_mains])
    await db_session.flush()

    # Items
    item1 = MenuItem(
        restaurant_id=restaurant.id,
        category_id=cat_starters.id,
        name="Paneer Tikka",
        price=Decimal("220.00"),
        is_available=True,
        display_order=1,
    )
    item2 = MenuItem(
        restaurant_id=restaurant.id,
        category_id=cat_mains.id,
        name="Butter Chicken",
        price=Decimal("340.00"),
        is_available=True,
        display_order=1,
    )
    db_session.add_all([item1, item2])
    await db_session.commit()

    return restaurant


@pytest.mark.asyncio
async def test_list_restaurants_api(
    async_client: AsyncClient, sample_restaurant_data: Restaurant
) -> None:
    """Test GET /api/v1/restaurants."""
    response = await async_client.get("/api/v1/restaurants")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["name"] == "Royal Spice"
    assert data[0]["id"] == str(sample_restaurant_data.id)


@pytest.mark.asyncio
async def test_get_restaurant_by_id_api(
    async_client: AsyncClient, sample_restaurant_data: Restaurant
) -> None:
    """Test GET /api/v1/restaurants/{restaurant_id}."""
    response = await async_client.get(f"/api/v1/restaurants/{sample_restaurant_data.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Royal Spice"
    assert data["phone_number"] == "+919876543210"


@pytest.mark.asyncio
async def test_get_restaurant_not_found(async_client: AsyncClient) -> None:
    """Test GET /api/v1/restaurants/{non_existent_id} returns 404."""
    random_id = uuid.uuid4()
    response = await async_client.get(f"/api/v1/restaurants/{random_id}")
    assert response.status_code == 404
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "RESTAURANT_NOT_FOUND"


@pytest.mark.asyncio
async def test_list_restaurant_tables_api(
    async_client: AsyncClient, sample_restaurant_data: Restaurant
) -> None:
    """Test GET /api/v1/restaurants/{restaurant_id}/tables."""
    response = await async_client.get(
        f"/api/v1/restaurants/{sample_restaurant_data.id}/tables"
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    table_numbers = {t["table_number"] for t in data}
    assert table_numbers == {"Table 1", "Table 2"}
    assert all("qr_token" in t for t in data)


@pytest.mark.asyncio
async def test_list_menu_categories_api(
    async_client: AsyncClient, sample_restaurant_data: Restaurant
) -> None:
    """Test GET /api/v1/restaurants/{restaurant_id}/menu/categories."""
    response = await async_client.get(
        f"/api/v1/restaurants/{sample_restaurant_data.id}/menu/categories"
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["name"] == "Starters"
    assert data[1]["name"] == "Main Course"


@pytest.mark.asyncio
async def test_list_menu_items_api(
    async_client: AsyncClient, sample_restaurant_data: Restaurant
) -> None:
    """Test GET /api/v1/restaurants/{restaurant_id}/menu/items."""
    response = await async_client.get(
        f"/api/v1/restaurants/{sample_restaurant_data.id}/menu/items"
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    item_names = {item["name"] for item in data}
    assert "Paneer Tikka" in item_names
    assert "Butter Chicken" in item_names
