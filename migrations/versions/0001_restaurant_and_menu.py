"""create restaurant and menu tables

Revision ID: 0001_create_restaurant_and_menu_tables
Revises: 
Create Date: 2026-09-19 11:05:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001_restaurant_and_menu"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Restaurants table
    op.create_table(
        "restaurants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("phone_number", sa.String(length=32), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_restaurants"),
    )
    op.create_index("ix_restaurants_name", "restaurants", ["name"])

    # 2. Restaurant Tables
    op.create_table(
        "restaurant_tables",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("restaurant_id", sa.Uuid(), nullable=False),
        sa.Column("table_number", sa.String(length=50), nullable=False),
        sa.Column("qr_token", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["restaurant_id"],
            ["restaurants.id"],
            name="fk_restaurant_tables_restaurant_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_restaurant_tables"),
        sa.UniqueConstraint("restaurant_id", "table_number", name="uq_restaurant_table_number"),
    )
    op.create_index("ix_restaurant_tables_restaurant_id", "restaurant_tables", ["restaurant_id"])
    op.create_index("ix_restaurant_tables_qr_token", "restaurant_tables", ["qr_token"], unique=True)

    # 3. Menu Categories
    op.create_table(
        "menu_categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("restaurant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["restaurant_id"],
            ["restaurants.id"],
            name="fk_menu_categories_restaurant_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_menu_categories"),
        sa.UniqueConstraint("id", "restaurant_id", name="uq_menu_category_id_restaurant"),
        sa.UniqueConstraint("restaurant_id", "name", name="uq_restaurant_category_name"),
    )
    op.create_index("ix_menu_categories_restaurant_id", "menu_categories", ["restaurant_id"])

    # 4. Menu Items
    op.create_table(
        "menu_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("restaurant_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("image_url", sa.String(length=500), nullable=True),
        sa.Column("is_available", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("display_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("price >= 0", name="chk_menu_item_price_positive"),
        sa.ForeignKeyConstraint(
            ["restaurant_id"],
            ["restaurants.id"],
            name="fk_menu_items_restaurant_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["category_id", "restaurant_id"],
            ["menu_categories.id", "menu_categories.restaurant_id"],
            name="fk_menu_item_category_restaurant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_menu_items"),
    )
    op.create_index("ix_menu_items_restaurant_id", "menu_items", ["restaurant_id"])
    op.create_index("ix_menu_items_category_id", "menu_items", ["category_id"])


def downgrade() -> None:
    op.drop_table("menu_items")
    op.drop_table("menu_categories")
    op.drop_table("restaurant_tables")
    op.drop_table("restaurants")
