import uuid
from datetime import datetime
from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """
    SQLAlchemy 2.0 declarative base.
    """
    pass


class TimestampMixin:
    """
    Mixin providing UTC created_at and updated_at timestamps.
    """
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class RestaurantScopedMixin:
    """
    Architectural foundation for multi-restaurant partitioning.
    Any restaurant-owned resource (tables, categories, menu items, orders)
    mixes in this class to guarantee restaurant tenant association.
    """
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        index=True,
        nullable=False,
        doc="Tenant restaurant identifier"
    )
