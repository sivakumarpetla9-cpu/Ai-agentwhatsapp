import secrets
import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class BillStatus(str, Enum):
    """
    Billing lifecycle states for a consolidated dining session bill.
    """
    OPEN = "OPEN"
    SETTLED = "SETTLED"
    VOID = "VOID"


def generate_bill_number() -> str:
    """
    Generate a concise, human-friendly bill reference for customer receipts and staff display.
    Example: BILL-A3F9B2
    """
    return f"BILL-{secrets.token_hex(3).upper()}"


class Bill(Base, TimestampMixin):
    """
    Consolidated bill entity representing all valid dining orders placed during a CustomerSession.
    Exactly one OPEN bill is allowed per session at any time.
    """
    __tablename__ = "bills"
    __table_args__ = (
        ForeignKeyConstraint(
            ["table_id", "restaurant_id"],
            ["restaurant_tables.id", "restaurant_tables.restaurant_id"],
            name="fk_bill_table_restaurant",
            ondelete="CASCADE",
        ),
        CheckConstraint("subtotal >= 0", name="chk_bill_subtotal_positive"),
        CheckConstraint("tax_amount >= 0", name="chk_bill_tax_amount_positive"),
        CheckConstraint("grand_total >= 0", name="chk_bill_grand_total_positive"),
        Index(
            "uq_bill_session_open",
            "session_id",
            unique=True,
            postgresql_where=text("status = 'OPEN'"),
            sqlite_where=text("status = 'OPEN'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique bill identifier",
    )
    bill_number: Mapped[str] = mapped_column(
        String(32),
        unique=True,
        nullable=False,
        index=True,
        default=generate_bill_number,
        doc="Human-friendly receipt and staff reference number (e.g. BILL-A1B2C3)",
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Associated tenant restaurant identifier",
    )
    table_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
        doc="Dining table where the session occurred",
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("customer_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Dining session to which this bill belongs",
    )
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
        doc="Total sum of all billable item line totals",
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
        doc="Calculated tax amount based on configured tax rate",
    )
    grand_total: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
        doc="Final payable amount (subtotal + tax_amount)",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=BillStatus.OPEN.value,
        nullable=False,
        index=True,
        doc="Bill lifecycle state (OPEN, SETTLED, VOID)",
    )
    settled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when table session was finalized and settled",
    )

    # Relationships
    session: Mapped["CustomerSession"] = relationship(  # type: ignore[name-defined]
        "CustomerSession",
        back_populates="bills",
        lazy="selectin",
    )
    restaurant: Mapped["Restaurant"] = relationship(  # type: ignore[name-defined]
        "Restaurant",
        foreign_keys=[restaurant_id],
        overlaps="bills,table",
        lazy="selectin",
    )
    table: Mapped["RestaurantTable"] = relationship(  # type: ignore[name-defined]
        "RestaurantTable",
        foreign_keys=[table_id],
        overlaps="bills,restaurant",
        lazy="selectin",
    )
    items: Mapped[List["BillItem"]] = relationship(
        "BillItem",
        back_populates="bill",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="BillItem.created_at",
    )

    @property
    def orders_included(self) -> List[uuid.UUID]:
        """
        Distinct list of Order IDs consolidated in this bill.
        """
        seen = set()
        order_ids = []
        for item in self.items:
            if item.order_id not in seen:
                seen.add(item.order_id)
                order_ids.append(item.order_id)
        return order_ids


class BillItem(Base, TimestampMixin):
    """
    Snapshotted line item belonging to a consolidated Bill.
    Preserves exact historical dish names, unit prices, and quantities.
    """
    __tablename__ = "bill_items"
    __table_args__ = (
        UniqueConstraint("bill_id", "order_item_id", name="uq_bill_item_order_item"),
        CheckConstraint("quantity > 0", name="chk_bill_item_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="chk_bill_item_price_positive"),
        CheckConstraint("line_total >= 0", name="chk_bill_item_line_total_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique bill item identifier",
    )
    bill_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("bills.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Parent consolidated bill identifier",
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Source order reference",
    )
    order_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("order_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Source order item reference",
    )
    item_name_snapshot: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Menu item name snapshotted at billing time",
    )
    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        doc="Quantity ordered (must be > 0)",
    )
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        doc="Snapshotted unit price",
    )
    line_total: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        doc="Snapshotted line total (quantity * unit_price)",
    )

    # Relationships
    bill: Mapped["Bill"] = relationship(
        "Bill",
        back_populates="items",
        lazy="selectin",
    )
    order: Mapped["Order"] = relationship(  # type: ignore[name-defined]
        "Order",
        lazy="selectin",
    )
    order_item: Mapped["OrderItem"] = relationship(  # type: ignore[name-defined]
        "OrderItem",
        lazy="selectin",
    )
