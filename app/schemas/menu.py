from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class MenuCategoryResponse(BaseModel):
    """
    Public response schema for MenuCategory entities.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Unique category identifier")
    restaurant_id: UUID = Field(..., description="Parent restaurant identifier")
    name: str = Field(..., description="Category display title")
    description: Optional[str] = Field(None, description="Category description")
    display_order: int = Field(..., description="Rendering order position")
    is_active: bool = Field(..., description="Category active status flag")
    created_at: datetime = Field(..., description="Record creation timestamp")
    updated_at: datetime = Field(..., description="Last record update timestamp")


class MenuItemResponse(BaseModel):
    """
    Public response schema for MenuItem entities.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Unique menu item identifier")
    restaurant_id: UUID = Field(..., description="Parent restaurant identifier")
    category_id: UUID = Field(..., description="Parent category identifier")
    name: str = Field(..., description="Item title")
    description: Optional[str] = Field(None, description="Item culinary description")
    price: Decimal = Field(..., description="Price in currency units")
    image_url: Optional[str] = Field(None, description="Item image URL")
    is_available: bool = Field(..., description="Kitchen availability flag")
    display_order: int = Field(..., description="Rendering order position inside category")
    created_at: datetime = Field(..., description="Record creation timestamp")
    updated_at: datetime = Field(..., description="Last record update timestamp")
