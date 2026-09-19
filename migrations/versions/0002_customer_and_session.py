"""create customer and customer session tables

Revision ID: 0002_customer_and_session
Revises: 0001_restaurant_and_menu
Create Date: 2026-09-19 11:47:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0002_customer_and_session"
down_revision: Union[str, None] = "0001_restaurant_and_menu"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add unique constraint on (id, restaurant_id) for restaurant_tables to enable composite foreign key
    with op.batch_alter_table("restaurant_tables") as batch_op:
        batch_op.create_unique_constraint(
            "uq_restaurant_tables_id_restaurant",
            ["id", "restaurant_id"],
        )

    # 2. Customers table
    op.create_table(
        "customers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("whatsapp_customer_id", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_customers"),
    )
    op.create_index("ix_customers_whatsapp_customer_id", "customers", ["whatsapp_customer_id"], unique=True)

    # 3. Customer Sessions table
    op.create_table(
        "customer_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("restaurant_id", sa.Uuid(), nullable=False),
        sa.Column("table_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="ACTIVE", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name="fk_customer_sessions_customer_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["restaurant_id"],
            ["restaurants.id"],
            name="fk_customer_sessions_restaurant_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["table_id", "restaurant_id"],
            ["restaurant_tables.id", "restaurant_tables.restaurant_id"],
            name="fk_customer_session_table_restaurant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_customer_sessions"),
    )
    op.create_index("ix_customer_sessions_customer_id", "customer_sessions", ["customer_id"])
    op.create_index("ix_customer_sessions_restaurant_id", "customer_sessions", ["restaurant_id"])
    op.create_index("ix_customer_sessions_table_id", "customer_sessions", ["table_id"])
    op.create_index("ix_customer_sessions_status", "customer_sessions", ["status"])


def downgrade() -> None:
    op.drop_table("customer_sessions")
    op.drop_table("customers")
    with op.batch_alter_table("restaurant_tables") as batch_op:
        batch_op.drop_constraint("uq_restaurant_tables_id_restaurant", type_="unique")
