import secrets
import uuid
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class OrderStatus(str, Enum):
    """
    Kitchen and dining lifecycle states for an order.
    Progression: NEW -> ACCEPTED -> PREPARING -> READY -> SERVED
    """
    NEW = "NEW"
    ACCEPTED = "ACCEPTED"
    PREPARING = "PREPARING"
    READY = "READY"
    SERVED = "SERVED"
    CANCELLED = "CANCELLED"


# Allowed state machine transitions
ALLOWED_TRANSITIONS: Dict[OrderStatus, List[OrderStatus]] = {
    OrderStatus.NEW: [OrderStatus.ACCEPTED, OrderStatus.CANCELLED],
    OrderStatus.ACCEPTED: [OrderStatus.PREPARING, OrderStatus.CANCELLED],
    OrderStatus.PREPARING: [OrderStatus.READY],
    OrderStatus.READY: [OrderStatus.SERVED],
    OrderStatus.SERVED: [],
    OrderStatus.CANCELLED: [],
}


def generate_order_number() -> str:
    """
    Generate a concise, human-friendly order identifier for staff and kitchen display.
    Example: ORD-A3F9B2
    """
    return f"ORD-{secrets.token_hex(3).upper()}"


class Order(Base, TimestampMixin):
    """
    Customer dine-in order placed from an active session cart.
    Follows the kitchen lifecycle from NEW to SERVED.
    """
    __tablename__ = "orders"
    __table_args__ = (
        ForeignKeyConstraint(
            ["table_id", "restaurant_id"],
            ["restaurant_tables.id", "restaurant_tables.restaurant_id"],
            name="fk_order_table_restaurant",
            ondelete="CASCADE",
        ),
        CheckConstraint("total_amount >= 0", name="chk_order_total_amount_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique order identifier"
    )
    order_number: Mapped[str] = mapped_column(
        String(32),
        unique=True,
        nullable=False,
        index=True,
        default=generate_order_number,
        doc="Human-friendly kitchen order reference"
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Associated tenant restaurant"
    )
    table_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
        doc="Dining table where the order was placed"
    )
    customer_session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("customer_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Active dining customer session that placed this order"
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=OrderStatus.NEW.value,
        nullable=False,
        index=True,
        doc="Current lifecycle state (NEW, ACCEPTED, PREPARING, READY, SERVED, CANCELLED)"
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        doc="Exact commercial order total snapshotted at placement"
    )
    special_instructions: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Optional customer preparation notes or allergy instructions"
    )

    # Relationships
    session: Mapped["CustomerSession"] = relationship(  # type: ignore[name-defined]
        "CustomerSession",
        back_populates="orders",
        lazy="selectin"
    )
    restaurant: Mapped["Restaurant"] = relationship(  # type: ignore[name-defined]
        "Restaurant",
        back_populates="orders",
        foreign_keys=[restaurant_id],
        overlaps="orders,table",
        lazy="selectin"
    )
    table: Mapped["RestaurantTable"] = relationship(  # type: ignore[name-defined]
        "RestaurantTable",
        foreign_keys=[table_id],
        overlaps="orders,restaurant",
        lazy="selectin"
    )
    items: Mapped[List["OrderItem"]] = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="OrderItem.created_at"
    )
    notifications: Mapped[List["OrderNotification"]] = relationship(  # type: ignore[name-defined]
        "OrderNotification",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="OrderNotification.created_at"
    )

    @property
    def item_count(self) -> int:
        """
        Total quantity of all items in this order.
        """
        return sum(item.quantity for item in self.items)


class OrderItem(Base, TimestampMixin):
    """
    Snapshotted line item belonging to a confirmed order.
    Preserves item name and unit price at time of order placement.
    """
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="chk_order_item_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="chk_order_item_price_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique order item identifier"
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Associated parent order"
    )
    menu_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("menu_items.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        doc="Associated menu item"
    )
    item_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Snapshotted menu item name at order placement"
    )
    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        doc="Quantity ordered (must be > 0)"
    )
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        doc="Snapshotted price at order placement"
    )

    # Relationships
    order: Mapped["Order"] = relationship(
        "Order",
        back_populates="items",
        lazy="selectin"
    )
    menu_item: Mapped["MenuItem"] = relationship(  # type: ignore[name-defined]
        "MenuItem",
        lazy="selectin"
    )

    @property
    def line_total(self) -> Decimal:
        """
        Calculate line total = quantity * unit_price.
        """
        return (Decimal(self.quantity) * self.unit_price).quantize(Decimal("0.01"))
