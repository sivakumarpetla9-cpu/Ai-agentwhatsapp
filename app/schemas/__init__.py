"""
Pydantic schemas for data validation and transfer.
"""
from app.schemas.health import HealthResponse
from app.schemas.common import ErrorDetail, ErrorResponse
from app.schemas.restaurant import RestaurantResponse, RestaurantTableResponse
from app.schemas.menu import MenuCategoryResponse, MenuItemResponse
from app.schemas.session import (
    SimpleRestaurantResponse,
    SimpleTableResponse,
    QREntryResponse,
    DirectTablesResponse,
    CreateSessionRequest,
    CreateQRSessionRequest,
    CustomerSessionResponse,
)
from app.schemas.customer_menu import (
    CustomerMenuItemResponse,
    CustomerCategoryResponse,
    CustomerFullMenuResponse,
)
from app.schemas.cart import (
    CartItemResponse,
    CartResponse,
    AddToCartRequest,
    UpdateCartItemRequest,
)

__all__ = [
    "HealthResponse",
    "ErrorDetail",
    "ErrorResponse",
    "RestaurantResponse",
    "RestaurantTableResponse",
    "MenuCategoryResponse",
    "MenuItemResponse",
    "SimpleRestaurantResponse",
    "SimpleTableResponse",
    "QREntryResponse",
    "DirectTablesResponse",
    "CreateSessionRequest",
    "CreateQRSessionRequest",
    "CustomerSessionResponse",
    "CustomerMenuItemResponse",
    "CustomerCategoryResponse",
    "CustomerFullMenuResponse",
    "CartItemResponse",
    "CartResponse",
    "AddToCartRequest",
    "UpdateCartItemRequest",
]
