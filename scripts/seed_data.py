"""
Development database seeding script.

Creates initial seed dataset for 'SpiceBox':
- 1 Restaurant (SpiceBox)
- 5 Tables (Table 1 to Table 5 with unique cryptographic QR tokens)
- 5 Categories (Starters, Main Course, Biryani, Drinks, Desserts)
- 8 Menu items with realistic prices

Must be run explicitly via:
  python scripts/seed_data.py
"""
import asyncio
import sys
from decimal import Decimal
from pathlib import Path
from typing import Optional

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from app.core.logging import setup_logging, get_logger
from app.database.session import async_session_factory
from app.models.restaurant import Restaurant, RestaurantTable, generate_qr_token
from app.models.menu import MenuCategory, MenuItem

setup_logging()
logger = get_logger("scripts.seed_data")


async def seed() -> None:
    async with async_session_factory() as session:
        # Check if SpiceBox already exists
        stmt = select(Restaurant).where(Restaurant.name == "SpiceBox")
        existing_res = (await session.execute(stmt)).scalars().first()

        if existing_res:
            logger.info(f"Restaurant 'SpiceBox' already exists with ID: {existing_res.id}. Skipping seed.")
            return

        logger.info("Seeding restaurant 'SpiceBox'...")
        restaurant = Restaurant(
            name="SpiceBox",
            description="Authentic Indian dining experience featuring slow-cooked biryanis and coastal delicacies.",
            phone_number="+919876543210",
            address="42 Culinary Avenue, Indiranagar, Bengaluru",
            is_active=True,
        )
        session.add(restaurant)
        await session.flush()

        logger.info(f"Created restaurant SpiceBox (id: {restaurant.id})")

        # 1. Create 5 Tables
        tables = []
        for i in range(1, 6):
            table = RestaurantTable(
                restaurant_id=restaurant.id,
                table_number=f"Table {i}",
                qr_token=generate_qr_token(),
                is_active=True,
            )
            tables.append(table)
            session.add(table)

        await session.flush()
        logger.info(f"Created {len(tables)} tables (Table 1 to Table 5)")

        # 2. Create Categories
        categories_data = [
            ("Starters", "Crispy and spicy appetizers to begin your feast", 1),
            ("Main Course", "Traditional curries and breads", 2),
            ("Biryani", "Dum-cooked fragrant basmati rice delicacies", 3),
            ("Drinks", "Chilled refreshments and coolers", 4),
            ("Desserts", "Sweet concluding treats", 5),
        ]
        category_map = {}
        for name, desc, order in categories_data:
            cat = MenuCategory(
                restaurant_id=restaurant.id,
                name=name,
                description=desc,
                display_order=order,
                is_active=True,
            )
            session.add(cat)
            category_map[name] = cat

        await session.flush()
        logger.info(f"Created {len(category_map)} menu categories")

        # 3. Create Menu Items
        menu_items_data = [
            # Category, Name, Description, Price, DisplayOrder
            ("Starters", "Chicken 65", "Crispy deep-fried chicken tossed in fiery curry leaf chili tempering", Decimal("240.00"), 1),
            ("Starters", "Paneer 65", "Spiced golden fried cottage cheese cubes garnished with coriander", Decimal("200.00"), 2),
            ("Biryani", "Chicken Biryani", "Aromatic long-grain basmati dum biryani with marinated tender chicken", Decimal("280.00"), 1),
            ("Biryani", "Mutton Biryani", "Slow-cooked succulent mutton pieces layered with saffron spiced rice", Decimal("360.00"), 2),
            ("Biryani", "Veg Biryani", "Seasonal farm vegetables simmered in fragrant whole spices and herbs", Decimal("220.00"), 3),
            ("Drinks", "Coke", "Classic chilled carbonated soda 330ml can", Decimal("40.00"), 1),
            ("Drinks", "Fresh Lime", "Refreshing freshly squeezed lime juice with mint and club soda", Decimal("60.00"), 2),
            ("Desserts", "Gulab Jamun", "Warm golden milk-solid dumplings soaked in rose and cardamom sugar syrup", Decimal("90.00"), 1),
        ]

        for cat_name, name, desc, price, order in menu_items_data:
            cat = category_map[cat_name]
            item = MenuItem(
                restaurant_id=restaurant.id,
                category_id=cat.id,
                name=name,
                description=desc,
                price=price,
                is_available=True,
                display_order=order,
            )
            session.add(item)

        await session.commit()
        logger.info(f"Created {len(menu_items_data)} menu items successfully.")
        print("\n=== Seeding Completed Successfully ===")
        print(f"Restaurant ID: {restaurant.id}")
        for t in tables:
            print(f"  Table: {t.table_number} | QR Token: {t.qr_token}")


if __name__ == "__main__":
    asyncio.run(seed())
