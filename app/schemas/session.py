from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class SimpleRestaurantResponse(BaseModel):
    """
    Public safe restaurant info for customer entry.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Restaurant identifier")
    name: str = Field(..., description="Restaurant name")


class SimpleTableResponse(BaseModel):
    """
    Public safe table info without exposing internal QR tokens.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Table identifier")
    table_number: str = Field(..., description="Table label or number")


class QREntryResponse(BaseModel):
    """
    Response schema for QR code resolution.
    Does NOT repeat the QR token or leak sensitive data.
    """
    restaurant: SimpleRestaurantResponse
    table: SimpleTableResponse


class DirectTablesResponse(BaseModel):
    """
    Response schema for direct WhatsApp table selection flow.
    Contains only active tables.
    """
    tables: List[SimpleTableResponse]


class CreateSessionRequest(BaseModel):
    """
    Request schema to create or resolve a session via direct table selection.
    """
    customer_session_identity: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Opaque or testing WhatsApp customer identifier supplied by integration",
        examples=["wa_cust_test_9876543210"]
    )
    restaurant_id: UUID = Field(..., description="Target restaurant identifier")
    table_id: UUID = Field(..., description="Selected table identifier")


class CreateQRSessionRequest(BaseModel):
    """
    Request schema to create or resolve a session via physical table QR token.
    """
    customer_session_identity: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Opaque or testing WhatsApp customer identifier supplied by integration",
        examples=["wa_cust_test_9876543210"]
    )
    qr_token: str = Field(..., min_length=1, max_length=64, description="Scanned table QR token")


class CustomerSessionResponse(BaseModel):
    """
    Safe public response schema for an active customer dining session.
    Never exposes internal WhatsApp customer phone numbers or tokens.
    """
    session_id: UUID = Field(..., description="Unique customer session identifier")
    restaurant_id: UUID = Field(..., description="Associated restaurant identifier")
    table_id: UUID = Field(..., description="Associated table identifier")
    status: str = Field(..., description="Session status (e.g. ACTIVE, EXPIRED)")
