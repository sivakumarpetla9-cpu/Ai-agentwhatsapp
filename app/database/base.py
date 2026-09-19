"""
Database metadata registry.
Imports all models so Alembic autogenerate discovers metadata properly.
"""
from app.models.base import Base
from app.models.restaurant import Restaurant, RestaurantTable
from app.models.menu import MenuCategory, MenuItem
from app.models.customer import Customer, CustomerSession
from app.models.cart import Cart, CartItem
from app.models.order import Order, OrderItem
from app.models.bill import Bill, BillItem
from app.models.order_notification import OrderNotification
from app.models.webhook_event import WebhookEvent

__all__ = [
    "Base",
    "Restaurant",
    "RestaurantTable",
    "MenuCategory",
    "MenuItem",
    "Customer",
    "CustomerSession",
    "Cart",
    "CartItem",
    "Order",
    "OrderItem",
    "Bill",
    "BillItem",
    "OrderNotification",
    "WebhookEvent",
]
