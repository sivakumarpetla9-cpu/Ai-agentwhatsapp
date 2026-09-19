"""create bills and bill items tables

Revision ID: 0005_bills_and_bill_items
Revises: 0004_orders_and_order_items
Create Date: 2026-09-19 13:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0005_bills_and_bill_items"
down_revision: Union[str, None] = "0004_orders_and_order_items"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Bills table
    op.create_table(
        "bills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("bill_number", sa.String(length=32), nullable=False),
        sa.Column("restaurant_id", sa.Uuid(), nullable=False),
        sa.Column("table_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=10, scale=2), server_default=sa.text("0.00"), nullable=False),
        sa.Column("tax_amount", sa.Numeric(precision=10, scale=2), server_default=sa.text("0.00"), nullable=False),
        sa.Column("grand_total", sa.Numeric(precision=10, scale=2), server_default=sa.text("0.00"), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="OPEN", nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("subtotal >= 0", name="chk_bill_subtotal_positive"),
        sa.CheckConstraint("tax_amount >= 0", name="chk_bill_tax_amount_positive"),
        sa.CheckConstraint("grand_total >= 0", name="chk_bill_grand_total_positive"),
        sa.ForeignKeyConstraint(
            ["restaurant_id"],
            ["restaurants.id"],
            name="fk_bills_restaurant_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["customer_sessions.id"],
            name="fk_bills_session_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["table_id", "restaurant_id"],
            ["restaurant_tables.id", "restaurant_tables.restaurant_id"],
            name="fk_bill_table_restaurant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_bills"),
        sa.UniqueConstraint("bill_number", name="uq_bills_bill_number"),
    )
    op.create_index("ix_bills_bill_number", "bills", ["bill_number"], unique=True)
    op.create_index("ix_bills_restaurant_id", "bills", ["restaurant_id"])
    op.create_index("ix_bills_table_id", "bills", ["table_id"])
    op.create_index("ix_bills_session_id", "bills", ["session_id"])
    op.create_index("ix_bills_status", "bills", ["status"])
    op.create_index("ix_bills_created_at", "bills", ["created_at"])
    op.create_index(
        "uq_bill_session_open",
        "bills",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
        sqlite_where=sa.text("status = 'OPEN'"),
    )

    # 2. Bill Items table
    op.create_table(
        "bill_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("bill_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("order_item_id", sa.Uuid(), nullable=False),
        sa.Column("item_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("quantity", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("line_total", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="chk_bill_item_quantity_positive"),
        sa.CheckConstraint("unit_price >= 0", name="chk_bill_item_price_positive"),
        sa.CheckConstraint("line_total >= 0", name="chk_bill_item_line_total_positive"),
        sa.ForeignKeyConstraint(
            ["bill_id"],
            ["bills.id"],
            name="fk_bill_items_bill_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name="fk_bill_items_order_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["order_item_id"],
            ["order_items.id"],
            name="fk_bill_items_order_item_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_bill_items"),
        sa.UniqueConstraint("bill_id", "order_item_id", name="uq_bill_item_order_item"),
    )
    op.create_index("ix_bill_items_bill_id", "bill_items", ["bill_id"])
    op.create_index("ix_bill_items_order_id", "bill_items", ["order_id"])
    op.create_index("ix_bill_items_order_item_id", "bill_items", ["order_item_id"])


def downgrade() -> None:
    op.drop_table("bill_items")
    op.drop_table("bills")
