import uuid
from datetime import datetime
from sqlalchemy import DateTime, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class WebhookEvent(Base, TimestampMixin):
    """
    Persistent log of inbound WhatsApp webhook message IDs.
    Enforces atomic idempotency across worker processes to prevent duplicate
    processing of repeated Meta webhook deliveries.
    """
    __tablename__ = "webhook_events"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        doc="Internal primary key",
    )
    message_id: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        index=True,
        nullable=False,
        doc="Meta WhatsApp message identifier (e.g. wamid.HBg...)",
    )
    from_phone_masked: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        doc="Privacy-masked sender identifier",
    )
    event_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="Type of event (text, interactive, etc.)",
    )
