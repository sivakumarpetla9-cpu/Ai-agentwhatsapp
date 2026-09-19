from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class CheckoutRequest(BaseModel):
    """
    Request payload to checkout an active customer session cart into a placed order.
    """
    session_id: UUID = Field(..., description="Active dining session identifier")
    special_instructions: Optional[str] = Field(
        None, max_length=500, description="Optional special cooking notes or allergy alerts"
    )


class OrderItemResponse(BaseModel):
    """
    Snapshotted order line item returned in order responses.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Order item identifier")
    menu_item_id: UUID = Field(..., description="Original menu item reference")
    item_name: str = Field(..., description="Menu item name snapshotted at order placement")
    quantity: int = Field(..., ge=1, description="Quantity ordered")
    unit_price: Decimal = Field(..., description="Unit price at order placement", max_digits=10, decimal_places=2)
    line_total: Decimal = Field(..., description="Total line amount (quantity * unit_price)", max_digits=10, decimal_places=2)


class OrderResponse(BaseModel):
    """
    Public customer-facing order response schema.
    PII safe: Never exposes customer WhatsApp phone number.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Unique order identifier")
    order_number: str = Field(..., description="Staff/kitchen friendly reference number (e.g. ORD-A1B2C3)")
    session_id: UUID = Field(..., description="Associated customer dining session")
    restaurant_id: UUID = Field(..., description="Tenant restaurant identifier")
    table_id: UUID = Field(..., description="Dining table identifier")
    table_number: str = Field(..., description="Physical table number (e.g. Table 1)")
    status: str = Field(..., description="Current order state (NEW, ACCEPTED, PREPARING, READY, SERVED, CANCELLED)")
    total_amount: Decimal = Field(..., description="Order total amount", max_digits=10, decimal_places=2)
    item_count: int = Field(..., ge=1, description="Total count of items in order")
    special_instructions: Optional[str] = Field(None, description="Customer notes or allergy instructions")
    items: List[OrderItemResponse] = Field(default_factory=list, description="List of snapshotted ordered items")
    created_at: datetime = Field(..., description="Order placement timestamp")
    updated_at: datetime = Field(..., description="Last status update timestamp")


class KitchenOrderStatusUpdateRequest(BaseModel):
    """
    Kitchen staff payload to advance or transition order status along the lifecycle.
    """
    restaurant_id: UUID = Field(..., description="Restaurant identifier verifying staff/kitchen ownership")
    status: str = Field(
        ...,
        description="Target status: ACCEPTED, PREPARING, READY, SERVED, CANCELLED",
    )


class KitchenOrderResponse(BaseModel):
    """
    Kitchen display system (KDS) order representation.
    Tailored for kitchen operations: exposes table number, order number, items, and notes.
    Never exposes customer WhatsApp identity.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Order identifier")
    order_number: str = Field(..., description="Order reference number")
    table_number: str = Field(..., description="Table designation where order will be served")
    status: str = Field(..., description="Current preparation state")
    item_count: int = Field(..., ge=1, description="Total item count")
    total_amount: Decimal = Field(..., description="Order total amount", max_digits=10, decimal_places=2)
    special_instructions: Optional[str] = Field(None, description="Kitchen notes or allergy instructions")
    items: List[OrderItemResponse] = Field(default_factory=list, description="Ordered items")
    created_at: datetime = Field(..., description="Timestamp order was received")
    updated_at: datetime = Field(..., description="Timestamp of last status transition")
