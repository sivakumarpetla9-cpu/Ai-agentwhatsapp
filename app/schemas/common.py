from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """
    Standard error detail envelope.
    """
    code: str = Field(..., description="Machine-readable error identifier", examples=["BAD_REQUEST"])
    message: str = Field(..., description="Human-readable error description")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Optional diagnostic details")


class ErrorResponse(BaseModel):
    """
    Standard error response body.
    """
    error: ErrorDetail
