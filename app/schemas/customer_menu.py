from decimal import Decimal
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class CustomerMenuItemResponse(BaseModel):
    """
    Public available menu item presented to the customer.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Unique menu item identifier")
    name: str = Field(..., description="Food or drink item name")
    description: Optional[str] = Field(None, description="Item description")
    price: Decimal = Field(..., description="Current price in currency units", max_digits=10, decimal_places=2)
    image_url: Optional[str] = Field(None, description="Optional food image URL")
    is_available: bool = Field(..., description="Availability status")
    display_order: int = Field(..., description="Sorting order")


class CustomerCategoryResponse(BaseModel):
    """
    Category containing active, selectable menu items for the customer.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Unique category identifier")
    name: str = Field(..., description="Category display title")
    description: Optional[str] = Field(None, description="Category description")
    display_order: int = Field(..., description="Display order position")
    items: List[CustomerMenuItemResponse] = Field(default_factory=list, description="Available items in this category")


class CustomerFullMenuResponse(BaseModel):
    """
    Complete active dining menu for the customer's active restaurant session.
    """
    restaurant_id: UUID = Field(..., description="Associated restaurant identifier")
    categories: List[CustomerCategoryResponse] = Field(default_factory=list, description="Ordered active categories")
