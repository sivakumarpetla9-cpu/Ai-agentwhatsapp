"""create orders and order items tables

Revision ID: 0004_orders_and_order_items
Revises: 0003_cart_and_cart_items
Create Date: 2026-09-19 12:47:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0004_orders_and_order_items"
down_revision: Union[str, None] = "0003_cart_and_cart_items"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Orders table
    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_number", sa.String(length=32), nullable=False),
        sa.Column("restaurant_id", sa.Uuid(), nullable=False),
        sa.Column("table_id", sa.Uuid(), nullable=False),
        sa.Column("customer_session_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="NEW", nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("special_instructions", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("total_amount >= 0", name="chk_order_total_amount_positive"),
        sa.ForeignKeyConstraint(
            ["restaurant_id"],
            ["restaurants.id"],
            name="fk_orders_restaurant_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["customer_session_id"],
            ["customer_sessions.id"],
            name="fk_orders_customer_session_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["table_id", "restaurant_id"],
            ["restaurant_tables.id", "restaurant_tables.restaurant_id"],
            name="fk_order_table_restaurant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_orders"),
        sa.UniqueConstraint("order_number", name="uq_orders_order_number"),
    )
    op.create_index("ix_orders_order_number", "orders", ["order_number"], unique=True)
    op.create_index("ix_orders_restaurant_id", "orders", ["restaurant_id"])
    op.create_index("ix_orders_table_id", "orders", ["table_id"])
    op.create_index("ix_orders_customer_session_id", "orders", ["customer_session_id"])
    op.create_index("ix_orders_status", "orders", ["status"])

    # 2. Order Items table
    op.create_table(
        "order_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("menu_item_id", sa.Uuid(), nullable=False),
        sa.Column("item_name", sa.String(length=255), nullable=False),
        sa.Column("quantity", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="chk_order_item_quantity_positive"),
        sa.CheckConstraint("unit_price >= 0", name="chk_order_item_price_positive"),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name="fk_order_items_order_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["menu_item_id"],
            ["menu_items.id"],
            name="fk_order_items_menu_item_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_order_items"),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    op.create_index("ix_order_items_menu_item_id", "order_items", ["menu_item_id"])


def downgrade() -> None:
    op.drop_table("order_items")
    op.drop_table("orders")
