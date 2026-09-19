from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class RestaurantResponse(BaseModel):
    """
    Public response schema for Restaurant entities.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Unique restaurant identifier")
    name: str = Field(..., description="Restaurant trade name")
    description: Optional[str] = Field(None, description="Restaurant description")
    phone_number: Optional[str] = Field(None, description="Contact telephone number")
    address: Optional[str] = Field(None, description="Physical location address")
    is_active: bool = Field(..., description="Operational status flag")
    created_at: datetime = Field(..., description="Record creation timestamp")
    updated_at: datetime = Field(..., description="Last record update timestamp")


class RestaurantTableResponse(BaseModel):
    """
    Public response schema for RestaurantTable entities.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Unique table identifier")
    restaurant_id: UUID = Field(..., description="Parent restaurant identifier")
    table_number: str = Field(..., description="Table number/label (e.g. Table 1)")
    qr_token: str = Field(..., description="Opaque secure token embedded in QR code")
    is_active: bool = Field(..., description="Table seating availability status")
    created_at: datetime = Field(..., description="Record creation timestamp")
    updated_at: datetime = Field(..., description="Last record update timestamp")
