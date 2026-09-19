import uuid
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Customer(Base, TimestampMixin):
    """
    Internal customer entity mapped to their WhatsApp identifier.
    The whatsapp_customer_id is treated as sensitive PII and must never be
    exposed in restaurant-facing responses or unmasked in application logs.
    """
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique internal customer identifier"
    )
    whatsapp_customer_id: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
        doc="Sensitive opaque or telephone WhatsApp customer identifier"
    )
    display_name: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        doc="Optional customer provided display name"
    )

    # Relationships
    sessions: Mapped[List["CustomerSession"]] = relationship(
        "CustomerSession",
        back_populates="customer",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="CustomerSession.created_at.desc()"
    )


class CustomerSession(Base, TimestampMixin):
    """
    Active or expired dining session binding a customer to a specific table at a restaurant.
    Cross-restaurant assignment is strictly prevented via composite foreign key constraint.
    """
    __tablename__ = "customer_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["table_id", "restaurant_id"],
            ["restaurant_tables.id", "restaurant_tables.restaurant_id"],
            name="fk_customer_session_table_restaurant",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique session identifier"
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Associated customer"
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Associated restaurant"
    )
    table_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
        doc="Associated table (must belong to the specified restaurant)"
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default="ACTIVE",
        nullable=False,
        index=True,
        doc="Session status: ACTIVE, EXPIRED, or CLOSED"
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp after which the session is considered expired"
    )

    # Relationships
    customer: Mapped["Customer"] = relationship(
        "Customer",
        back_populates="sessions",
        lazy="selectin"
    )
    restaurant: Mapped["Restaurant"] = relationship(  # type: ignore[name-defined]
        "Restaurant",
        back_populates="sessions",
        foreign_keys=[restaurant_id],
        overlaps="sessions,table",
        lazy="selectin"
    )
    table: Mapped["RestaurantTable"] = relationship(  # type: ignore[name-defined]
        "RestaurantTable",
        back_populates="sessions",
        foreign_keys=[table_id],
        overlaps="sessions,restaurant",
        lazy="selectin"
    )
    cart: Mapped[Optional["Cart"]] = relationship(  # type: ignore[name-defined]
        "Cart",
        back_populates="session",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin"
    )
    orders: Mapped[List["Order"]] = relationship(  # type: ignore[name-defined]
        "Order",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="Order.created_at.desc()",
        lazy="selectin"
    )
    bills: Mapped[List["Bill"]] = relationship(  # type: ignore[name-defined]
        "Bill",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="Bill.created_at.desc()",
        lazy="selectin"
    )

    @property
    def is_currently_active(self) -> bool:
        """
        Check whether the session is active and not expired.
        """
        if self.status != "ACTIVE":
            return False
        if self.expires_at is not None:
            now = datetime.now(timezone.utc)
            # Ensure comparison is timezone-aware
            exp = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=timezone.utc)
            if exp <= now:
                return False
        return True
