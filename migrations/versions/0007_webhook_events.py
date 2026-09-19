"""create webhook_events table for persistent idempotency

Revision ID: 0007_webhook_events
Revises: 0006_order_notifications
Create Date: 2026-09-19 16:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0007_webhook_events"
down_revision: Union[str, None] = "0006_order_notifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.String(length=128), nullable=False),
        sa.Column("from_phone_masked", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_events")),
    )
    op.create_index(op.f("ix_webhook_events_message_id"), "webhook_events", ["message_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_webhook_events_message_id"), table_name="webhook_events")
    op.drop_table("webhook_events")
