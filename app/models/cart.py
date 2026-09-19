import uuid
from decimal import Decimal
from typing import List, Optional
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Cart(Base, TimestampMixin):
    """
    Shopping cart belonging strictly to an active CustomerSession.
    At most one active cart exists per customer session.
    """
    __tablename__ = "carts"
    __table_args__ = (
        UniqueConstraint("customer_session_id", name="uq_cart_customer_session"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique cart identifier"
    )
    customer_session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("customer_sessions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
        doc="Associated customer dining session"
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default="ACTIVE",
        nullable=False,
        index=True,
        doc="Cart status (ACTIVE, CHECKED_OUT, ABANDONED)"
    )

    # Relationships
    session: Mapped["CustomerSession"] = relationship(  # type: ignore[name-defined]
        "CustomerSession",
        back_populates="cart",
        lazy="selectin"
    )
    items: Mapped[List["CartItem"]] = relationship(
        "CartItem",
        back_populates="cart",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="CartItem.created_at"
    )

    @property
    def subtotal(self) -> Decimal:
        """
        Calculate total sum of all item line totals using exact Decimal arithmetic.
        """
        total = sum((item.line_total for item in self.items), Decimal("0.00"))
        return total.quantize(Decimal("0.01"))

    @property
    def item_count(self) -> int:
        """
        Calculate total count of individual food items in cart.
        """
        return sum(item.quantity for item in self.items)


class CartItem(Base, TimestampMixin):
    """
    Line item inside an active shopping cart.
    Snapshots the menu item's unit_price at the time of addition.
    """
    __tablename__ = "cart_items"
    __table_args__ = (
        UniqueConstraint("cart_id", "menu_item_id", name="uq_cart_item_cart_menu_item"),
        CheckConstraint("quantity > 0", name="chk_cart_item_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="chk_cart_item_price_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique cart item identifier"
    )
    cart_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("carts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Associated parent cart"
    )
    menu_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("menu_items.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        doc="Associated menu item"
    )
    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        doc="Order item quantity (must be > 0)"
    )
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        doc="Snapshotted price at the time of addition"
    )

    # Relationships
    cart: Mapped["Cart"] = relationship(
        "Cart",
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
