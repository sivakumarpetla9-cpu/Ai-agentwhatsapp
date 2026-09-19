"""create order_notifications table

Revision ID: 0006_order_notifications
Revises: 0005_bills_and_bill_items
Create Date: 2026-09-19 14:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0006_order_notifications"
down_revision: Union[str, None] = "0005_bills_and_bill_items"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "order_notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("notification_type", sa.String(length=50), server_default="STATUS_UPDATE", nullable=False),
        sa.Column("recipient_reference", sa.String(length=64), nullable=False),
        sa.Column("delivery_status", sa.String(length=20), server_default="PENDING", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name="fk_order_notifications_order_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_order_notifications"),
        sa.UniqueConstraint(
            "order_id",
            "status",
            "notification_type",
            name="uq_order_notification_order_status_type",
        ),
    )
    op.create_index(
        "ix_order_notifications_order_id",
        "order_notifications",
        ["order_id"],
        unique=False,
    )
    op.create_index(
        "ix_order_notifications_status",
        "order_notifications",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_order_notifications_delivery_status",
        "order_notifications",
        ["delivery_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_order_notifications_delivery_status", table_name="order_notifications")
    op.drop_index("ix_order_notifications_status", table_name="order_notifications")
    op.drop_index("ix_order_notifications_order_id", table_name="order_notifications")
    op.drop_table("order_notifications")
