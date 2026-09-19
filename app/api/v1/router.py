from fastapi import APIRouter
from app.api.v1.endpoints import (
    billing,
    cart,
    entry,
    health,
    kitchen,
    menu,
    orders,
    restaurants,
    sessions,
)

from app.integrations.whatsapp import whatsapp_router

api_router = APIRouter()

# Include version 1 endpoint routers
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(restaurants.router, prefix="/restaurants", tags=["Restaurants"])
api_router.include_router(entry.router, prefix="/entry", tags=["Customer Entry"])
api_router.include_router(sessions.router, prefix="/sessions", tags=["Customer Sessions"])
api_router.include_router(menu.router, prefix="/menu", tags=["Customer Menu"])
api_router.include_router(cart.router, prefix="/cart", tags=["Customer Cart"])
api_router.include_router(orders.router, prefix="/orders", tags=["Customer Orders"])
api_router.include_router(kitchen.router, prefix="/kitchen", tags=["Kitchen & Staff"])
api_router.include_router(billing.router, prefix="/billing", tags=["Billing & Settlement"])
api_router.include_router(
    whatsapp_router,
    prefix="/integrations/whatsapp",
    tags=["WhatsApp Webhook"],
)

