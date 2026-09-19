from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class GenerateBillRequest(BaseModel):
    """
    Request payload to generate or retrieve an active OPEN bill for a customer session.
    """
    session_id: UUID = Field(..., description="Active dining session identifier")


class SettleBillRequest(BaseModel):
    """
    Optional payload for bill settlement, verifying restaurant tenant or customer session scope.
    """
    restaurant_id: Optional[UUID] = Field(None, description="Optional tenant restaurant ID for staff authorization")
    session_id: Optional[UUID] = Field(None, description="Optional session ID for customer authorization")


class BillItemResponse(BaseModel):
    """
    Snapshotted billing line item returned in consolidated bill responses.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Unique bill item identifier")
    order_id: UUID = Field(..., description="Source order identifier")
    order_item_id: UUID = Field(..., description="Source order item identifier")
    item_name_snapshot: str = Field(..., description="Dish name snapshotted at billing time")
    quantity: int = Field(..., ge=1, description="Quantity ordered")
    unit_price: Decimal = Field(..., description="Unit price snapshotted", max_digits=10, decimal_places=2)
    line_total: Decimal = Field(..., description="Line total amount", max_digits=10, decimal_places=2)


class BillResponse(BaseModel):
    """
    Consolidated session bill response.
    Privacy safe: never exposes customer phone number or sensitive PII.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Unique bill identifier")
    bill_number: str = Field(..., description="Human-friendly receipt and staff reference (e.g. BILL-A1B2C3)")
    restaurant_id: UUID = Field(..., description="Tenant restaurant identifier")
    table_id: UUID = Field(..., description="Dining table identifier")
    table_number: str = Field(..., description="Physical table number (e.g. Table 1)")
    session_id: UUID = Field(..., description="Associated customer dining session identifier")
    orders_included: List[UUID] = Field(default_factory=list, description="List of Order IDs included in this bill")
    items: List[BillItemResponse] = Field(default_factory=list, description="Consolidated snapshotted bill items")
    subtotal: Decimal = Field(..., description="Sum of all bill line totals", max_digits=10, decimal_places=2)
    tax_amount: Decimal = Field(..., description="Calculated tax amount", max_digits=10, decimal_places=2)
    grand_total: Decimal = Field(..., description="Final total payable amount (subtotal + tax)", max_digits=10, decimal_places=2)
    status: str = Field(..., description="Bill lifecycle state (OPEN, SETTLED, VOID)")
    created_at: datetime = Field(..., description="Bill generation timestamp")
    settled_at: Optional[datetime] = Field(None, description="Settlement timestamp if finalized")
