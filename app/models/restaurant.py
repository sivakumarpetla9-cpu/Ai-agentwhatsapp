import secrets
import uuid
from typing import List, Optional
from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


def generate_qr_token() -> str:
    """
    Generate a high-entropy, cryptographically secure token for table QR identification.
    Decoupled from table numbers to prevent table spoofing.
    """
    return secrets.token_urlsafe(24)


class Restaurant(Base, TimestampMixin):
    """
    Restaurant entity representing a tenant business.
    """
    __tablename__ = "restaurants"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique restaurant identifier"
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        doc="Name of the restaurant"
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Detailed description or tagline"
    )
    phone_number: Mapped[Optional[str]] = mapped_column(
        String(32),
        nullable=True,
        doc="Official restaurant contact phone number"
    )
    address: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Physical dining location address"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        doc="Operational status flag"
    )

    # Relationships
    tables: Mapped[List["RestaurantTable"]] = relationship(
        "RestaurantTable",
        back_populates="restaurant",
        cascade="all, delete-orphan",
        order_by="RestaurantTable.table_number",
        lazy="selectin",
    )
    categories: Mapped[List["MenuCategory"]] = relationship(  # type: ignore[name-defined]
        "MenuCategory",
        back_populates="restaurant",
        cascade="all, delete-orphan",
        order_by="MenuCategory.display_order",
        lazy="selectin",
    )
    menu_items: Mapped[List["MenuItem"]] = relationship(  # type: ignore[name-defined]
        "MenuItem",
        back_populates="restaurant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    sessions: Mapped[List["CustomerSession"]] = relationship(  # type: ignore[name-defined]
        "CustomerSession",
        back_populates="restaurant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    orders: Mapped[List["Order"]] = relationship(  # type: ignore[name-defined]
        "Order",
        back_populates="restaurant",
        cascade="all, delete-orphan",
        order_by="Order.created_at.desc()",
        lazy="selectin",
    )
    bills: Mapped[List["Bill"]] = relationship(  # type: ignore[name-defined]
        "Bill",
        back_populates="restaurant",
        cascade="all, delete-orphan",
        order_by="Bill.created_at.desc()",
        lazy="selectin",
    )


class RestaurantTable(Base, TimestampMixin):
    """
    Physical dining table belonging to a specific restaurant.
    """
    __tablename__ = "restaurant_tables"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "table_number", name="uq_restaurant_table_number"),
        UniqueConstraint("id", "restaurant_id", name="uq_restaurant_tables_id_restaurant"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique table identifier"
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Associated restaurant identifier"
    )
    table_number: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="Visible table designation (e.g. Table 1, Table 12)"
    )
    qr_token: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
        default=generate_qr_token,
        doc="Secure opaque token embedded in QR code"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        doc="Table seating availability status"
    )

    # Relationships
    restaurant: Mapped["Restaurant"] = relationship(
        "Restaurant",
        back_populates="tables",
        lazy="selectin",
    )
    sessions: Mapped[List["CustomerSession"]] = relationship(  # type: ignore[name-defined]
        "CustomerSession",
        back_populates="table",
        cascade="all, delete-orphan",
        overlaps="sessions",
        lazy="selectin",
    )
