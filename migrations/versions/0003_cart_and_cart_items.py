"""create cart and cart items tables

Revision ID: 0003_cart_and_cart_items
Revises: 0002_customer_and_session
Create Date: 2026-09-19 12:17:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0003_cart_and_cart_items"
down_revision: Union[str, None] = "0002_customer_and_session"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Carts table
    op.create_table(
        "carts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("customer_session_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="ACTIVE", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["customer_session_id"],
            ["customer_sessions.id"],
            name="fk_carts_customer_session_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_carts"),
        sa.UniqueConstraint("customer_session_id", name="uq_cart_customer_session"),
    )
    op.create_index("ix_carts_customer_session_id", "carts", ["customer_session_id"])
    op.create_index("ix_carts_status", "carts", ["status"])

    # 2. Cart Items table
    op.create_table(
        "cart_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("cart_id", sa.Uuid(), nullable=False),
        sa.Column("menu_item_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="chk_cart_item_quantity_positive"),
        sa.CheckConstraint("unit_price >= 0", name="chk_cart_item_price_positive"),
        sa.ForeignKeyConstraint(
            ["cart_id"],
            ["carts.id"],
            name="fk_cart_items_cart_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["menu_item_id"],
            ["menu_items.id"],
            name="fk_cart_items_menu_item_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cart_items"),
        sa.UniqueConstraint("cart_id", "menu_item_id", name="uq_cart_item_cart_menu_item"),
    )
    op.create_index("ix_cart_items_cart_id", "cart_items", ["cart_id"])
    op.create_index("ix_cart_items_menu_item_id", "cart_items", ["menu_item_id"])


def downgrade() -> None:
    op.drop_table("cart_items")
    op.drop_table("carts")
