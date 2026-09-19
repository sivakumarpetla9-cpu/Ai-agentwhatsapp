from decimal import Decimal
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class CartItemResponse(BaseModel):
    """
    Public response schema for an individual line item inside a cart.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Unique cart item identifier")
    menu_item_id: UUID = Field(..., description="Menu item identifier")
    name: str = Field(..., description="Item display name")
    quantity: int = Field(..., ge=1, description="Quantity ordered")
    unit_price: Decimal = Field(..., description="Unit price at time item was added", max_digits=10, decimal_places=2)
    line_total: Decimal = Field(..., description="Total price for this line item", max_digits=10, decimal_places=2)


class CartResponse(BaseModel):
    """
    Full active shopping cart response schema with server-calculated subtotal and item count.
    """
    model_config = ConfigDict(from_attributes=True)

    cart_id: UUID = Field(..., description="Unique cart identifier")
    session_id: UUID = Field(..., description="Associated customer session identifier")
    items: List[CartItemResponse] = Field(default_factory=list, description="List of items in the cart")
    subtotal: Decimal = Field(..., description="Total amount for all items in cart", max_digits=10, decimal_places=2)
    item_count: int = Field(..., ge=0, description="Total count of items in the cart")


class AddToCartRequest(BaseModel):
    """
    Request payload to add a menu item to the active session cart.
    """
    session_id: Optional[UUID] = Field(None, description="Active session ID (optional if supplied via X-Session-ID header)")
    menu_item_id: UUID = Field(..., description="Menu item to add to the cart")
    quantity: int = Field(1, ge=1, description="Quantity of item to add (must be > 0)")


class UpdateCartItemRequest(BaseModel):
    """
    Request payload to update the quantity of an item in the cart.
    """
    quantity: int = Field(..., ge=1, description="Updated quantity (must be > 0; use DELETE to remove)")
