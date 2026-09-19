from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Meta / WhatsApp Cloud API Inbound Webhook Schemas
# ---------------------------------------------------------------------------

class WhatsAppTextMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    body: str = Field(..., description="Message text content")


class WhatsAppInteractiveButtonReply(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(..., description="Unique callback identifier for the button")
    title: str = Field(..., description="Visible button title")


class WhatsAppInteractiveListReply(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(..., description="Unique row identifier")
    title: str = Field(..., description="Visible row title")
    description: Optional[str] = Field(None, description="Optional row description")


class WhatsAppInteractive(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: str = Field(..., description="Type of interactive reply: button_reply or list_reply")
    button_reply: Optional[WhatsAppInteractiveButtonReply] = None
    list_reply: Optional[WhatsAppInteractiveListReply] = None


class WhatsAppInboundMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    from_: str = Field(..., alias="from", description="Customer telephone WhatsApp identifier (e.g. +919876543210)")
    id: str = Field(..., description="Unique message ID assigned by WhatsApp")
    timestamp: str = Field(..., description="Message epoch timestamp string")
    type: str = Field(..., description="Message type: text, interactive, etc.")
    text: Optional[WhatsAppTextMessage] = None
    interactive: Optional[WhatsAppInteractive] = None


class WhatsAppContactProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: Optional[str] = None


class WhatsAppContact(BaseModel):
    model_config = ConfigDict(extra="ignore")
    profile: Optional[WhatsAppContactProfile] = None
    wa_id: str = Field(..., description="WhatsApp user ID")


class WhatsAppValue(BaseModel):
    model_config = ConfigDict(extra="ignore")
    messaging_product: str = "whatsapp"
    metadata: Optional[Dict[str, Any]] = None
    contacts: Optional[List[WhatsAppContact]] = None
    messages: Optional[List[WhatsAppInboundMessage]] = None


class WhatsAppChange(BaseModel):
    model_config = ConfigDict(extra="ignore")
    field: str
    value: WhatsAppValue


class WhatsAppEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    changes: List[WhatsAppChange]


class WhatsAppWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    object: str = "whatsapp_business_account"
    entry: List[WhatsAppEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Outbound Message Representation Models
# ---------------------------------------------------------------------------

class OutboundMessageRecord(BaseModel):
    """
    Standard record of an outbound message dispatched to a customer.
    Used for live sending and test assertions.
    """
    to: str = Field(..., description="Destination masked or telephone identifier")
    type: str = Field(..., description="text, button, or list")
    body: str = Field(..., description="Body text of the message")
    buttons: Optional[List[Dict[str, str]]] = None
    sections: Optional[List[Dict[str, Any]]] = None
    meta_message_id: Optional[str] = Field(None, description="Meta Cloud API assigned message ID (wamid...)")
    success: bool = Field(True, description="Whether dispatch succeeded")
    error: Optional[str] = Field(None, description="Sanitized error description if dispatch failed")
    payload: Optional[Dict[str, Any]] = Field(None, description="Normalized payload sent to Meta API")


# ---------------------------------------------------------------------------
# Meta Cloud API Outbound Response Schemas
# ---------------------------------------------------------------------------

class MetaMessageContact(BaseModel):
    model_config = ConfigDict(extra="ignore")
    input: str
    wa_id: str


class MetaMessageCreated(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    message_status: Optional[str] = None


class MetaMessageSuccessResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    messaging_product: str = "whatsapp"
    contacts: List[MetaMessageContact] = Field(default_factory=list)
    messages: List[MetaMessageCreated] = Field(default_factory=list)


class MetaErrorDetail(BaseModel):
    model_config = ConfigDict(extra="ignore")
    message: str
    type: Optional[str] = None
    code: Optional[int] = None
    error_data: Optional[Dict[str, Any]] = None
    fbtrace_id: Optional[str] = None


class MetaErrorResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    error: MetaErrorDetail

