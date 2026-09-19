import uuid
from decimal import Decimal
from typing import List, Optional
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class MenuCategory(Base, TimestampMixin):
    """
    Menu Category grouping related dishes (e.g., Starters, Main Course, Biryani).
    Belongs strictly to one restaurant.
    """
    __tablename__ = "menu_categories"
    __table_args__ = (
        UniqueConstraint("id", "restaurant_id", name="uq_menu_category_id_restaurant"),
        UniqueConstraint("restaurant_id", "name", name="uq_restaurant_category_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique category identifier"
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Associated restaurant identifier"
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="Category name (e.g. Starters, Biryani)"
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Optional category description"
    )
    display_order: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Sort order for menu rendering"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        doc="Visibility status flag"
    )

    # Relationships
    restaurant: Mapped["Restaurant"] = relationship(  # type: ignore[name-defined]
        "Restaurant",
        back_populates="categories",
        lazy="selectin",
    )
    items: Mapped[List["MenuItem"]] = relationship(
        "MenuItem",
        back_populates="category",
        foreign_keys="MenuItem.category_id",
        overlaps="menu_items,restaurant",
        order_by="MenuItem.display_order",
        lazy="selectin",
    )


class MenuItem(Base, TimestampMixin):
    """
    Individual food or beverage item offered on a restaurant's menu.
    Belongs strictly to one restaurant and one category owned by that same restaurant.
    """
    __tablename__ = "menu_items"
    __table_args__ = (
        CheckConstraint("price >= 0", name="chk_menu_item_price_positive"),
        ForeignKeyConstraint(
            ["category_id", "restaurant_id"],
            ["menu_categories.id", "menu_categories.restaurant_id"],
            name="fk_menu_item_category_restaurant",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
        doc="Unique menu item identifier"
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Associated restaurant identifier"
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
        doc="Associated category identifier (must belong to same restaurant)"
    )
    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        doc="Name of the food or beverage item"
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Culinary description, ingredients, or preparation details"
    )
    price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        doc="Item price in currency units (must be non-negative)"
    )
    image_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        doc="Optional public CDN/hosted image URL"
    )
    is_available: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        doc="Current kitchen availability (avoids deleting historical items)"
    )
    display_order: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Sort order within the category"
    )

    # Relationships
    restaurant: Mapped["Restaurant"] = relationship(  # type: ignore[name-defined]
        "Restaurant",
        back_populates="menu_items",
        foreign_keys=[restaurant_id],
        overlaps="category,items",
        lazy="selectin",
    )
    category: Mapped["MenuCategory"] = relationship(
        "MenuCategory",
        back_populates="items",
        foreign_keys=[category_id],
        overlaps="menu_items,restaurant",
        lazy="selectin",
    )
