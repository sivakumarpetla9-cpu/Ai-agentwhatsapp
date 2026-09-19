import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class OrderNotification(Base, TimestampMixin):
    """
    Persistent record of an outbound customer notification attempt for an order status change.
    Guarantees idempotency via unique constraint on (order_id, status, notification_type).
    """
    __tablename__ = "order_notifications"
    __table_args__ = (
        UniqueConstraint(
            "order_id",
            "status",
            "notification_type",
            name="uq_order_notification_order_status_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique notification identifier",
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Associated order",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        doc="Order lifecycle status that triggered this notification (e.g. ACCEPTED, PREPARING, READY, SERVED, CANCELLED)",
    )
    notification_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="STATUS_UPDATE",
        doc="Type of notification dispatched (e.g. STATUS_UPDATE)",
    )
    recipient_reference: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="Masked recipient phone number or internal customer identifier (never raw unmasked PII)",
    )
    delivery_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="PENDING",
        index=True,
        doc="Delivery state: PENDING, SENT, FAILED",
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Sanitized error message if dispatch failed",
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when message was successfully dispatched",
    )

    # Relationship to Order
    order: Mapped["Order"] = relationship(  # type: ignore[name-defined]
        "Order",
        back_populates="notifications",
        lazy="selectin",
    )
