from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """
    Standard health check response schema.
    """
    status: str = Field(default="ok", description="Service health status", examples=["ok"])
