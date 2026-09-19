"""
Interactive CLI WhatsApp Chat Simulator for Dine-In Restaurant Ordering.
Simulates customer WhatsApp conversations and kitchen management locally.

Run with:
    python scripts/simulate_chat.py
"""
import argparse
import asyncio
import os
import re
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

# Ensure safe UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import event, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.database.session import async_session_factory
from app.integrations.whatsapp.bot import WhatsAppBotEngine
from app.integrations.whatsapp.client import WhatsAppClient, whatsapp_client
from app.models.base import Base
from app.models.bill import Bill
from app.models.customer import Customer, CustomerSession
from app.models.menu import MenuCategory, MenuItem
from app.models.order import Order, OrderItem, OrderStatus
from app.models.restaurant import Restaurant, RestaurantTable, generate_qr_token
from app.repositories.customer import CustomerRepository, CustomerSessionRepository
from app.repositories.menu import MenuCategoryRepository, MenuItemRepository
from app.repositories.order import OrderRepository
from app.repositories.restaurant import RestaurantRepository, RestaurantTableRepository
from app.services.billing import BillingService
from app.services.cart import CartService
from app.services.customer_menu import CustomerMenuService
from app.services.order import OrderService
from app.services.order_notifications import OrderNotificationService
from app.services.session import SessionService, mask_identifier

settings = get_settings()


class WhatsAppSimulator:
    """
    Terminal adapter driving existing backend domain services and the WhatsApp Bot Engine.
    Does not duplicate cart, order, billing, or state machine logic.
    """

    DEFAULT_PHONE = "+919999888877"

    def __init__(
        self,
        session: AsyncSession,
        customer_phone: Optional[str] = None,
        client: Optional[WhatsAppClient] = None,
    ) -> None:
        self.session = session
        self.client = client or whatsapp_client
        self.customer_phone = customer_phone or self.DEFAULT_PHONE

        # Existing domain services and repos
        self.restaurant_repo = RestaurantRepository(session)
        self.table_repo = RestaurantTableRepository(session)
        self.customer_repo = CustomerRepository(session)
        self.session_repo = CustomerSessionRepository(session)
        self.order_repo = OrderRepository(session)

        self.session_service = SessionService(session)
        self.menu_service = CustomerMenuService(session)
        self.cart_service = CartService(session)
        self.order_service = OrderService(session)
        self.billing_service = BillingService(session)
        self.notification_service = OrderNotificationService(session, self.client)
        self.bot_engine = WhatsAppBotEngine(session, self.client)

        # Simulator runtime context
        self.restaurant: Optional[Restaurant] = None
        self.current_session_id: Optional[UUID] = None
        self.last_sent_count = len(self.client.sent_messages)

        # In-memory selection caches for natural numeric CLI commands
        self.table_map: Dict[int, RestaurantTable] = {}
        self.category_map: Dict[int, Any] = {}
        self.item_map: Dict[int, Any] = {}
        self.cart_item_map: Dict[int, Any] = {}

    def _get_new_outbound_messages(self) -> List[Any]:
        """
        Fetch any new outbound WhatsApp messages dispatched since last check.
        """
        current_count = len(self.client.sent_messages)
        if current_count > self.last_sent_count:
            new_msgs = self.client.sent_messages[self.last_sent_count : current_count]
            self.last_sent_count = current_count
            return new_msgs
        return []

    def _format_outbound_notifications(self) -> str:
        """
        Format any new outbound WhatsApp messages into a visible terminal alert box.
        """
        new_msgs = self._get_new_outbound_messages()
        if not new_msgs:
            return ""

        blocks = []
        for msg in new_msgs:
            body_clean = msg.body.strip()
            blocks.append(
                "----------------------------------------\n"
                " OUTBOUND WHATSAPP\n"
                "----------------------------------------\n"
                f"{body_clean}\n"
                "----------------------------------------"
            )
        return "\n" + "\n".join(blocks)

    async def initialize(self) -> str:
        """
        Initialize simulator, load or pick restaurant, and ensure customer record exists.
        """
        # Load restaurants
        restaurants = await self.restaurant_repo.list_active()
        if not restaurants:
            return "⚠️ No active restaurants found in the database. Please run scripts/seed_data.py."

        # Prioritize SpiceBox if present, otherwise first active restaurant
        spicebox = next((r for r in restaurants if r.name.lower() == "spicebox"), None)
        self.restaurant = spicebox if spicebox else restaurants[0]

        # Check for existing active session for this customer
        customer = await self.customer_repo.get_by_whatsapp_id(self.customer_phone)
        if customer:
            active_sess = await self.session_repo.get_active_session_for_customer(customer.id)
            if active_sess and active_sess.restaurant_id == self.restaurant.id:
                self.current_session_id = active_sess.id

        db_type = "PostgreSQL"
        if self.session.bind and hasattr(self.session.bind, "dialect"):
            dialect_name = self.session.bind.dialect.name.lower()
            db_type = "SQLite" if "sqlite" in dialect_name else "PostgreSQL"

        out = [
            "==================================================",
            " WhatsApp Restaurant Ordering Simulator",
            "==================================================",
            f"Restaurant: {self.restaurant.name}",
            f"Database: LOCAL ({db_type})",
            "WhatsApp: LOCAL MOCK",
            f"Simulated Customer: {mask_identifier(self.customer_phone)}",
            "",
            'Type "help" for commands. Type "exit" to quit.',
            "==================================================",
        ]
        if self.current_session_id:
            out.append(f"✓ Resumed active session at {self.restaurant.name}.")
        else:
            out.append('Please start by scanning a table QR ("qr") or choosing a table ("tables").')
        return "\n".join(out)

    async def select_restaurant(self, restaurant_id_or_num: str) -> str:
        """
        Switch active restaurant context.
        """
        restaurants = await self.restaurant_repo.list_active()
        chosen = None
        if restaurant_id_or_num.isdigit():
            idx = int(restaurant_id_or_num)
            if 1 <= idx <= len(restaurants):
                chosen = restaurants[idx - 1]
        else:
            for r in restaurants:
                if str(r.id) == restaurant_id_or_num or r.name.lower() == restaurant_id_or_num.lower():
                    chosen = r
                    break

        if not chosen:
            return f"Restaurant '{restaurant_id_or_num}' not found."

        self.restaurant = chosen
        self.current_session_id = None
        return f"Switched to restaurant: {self.restaurant.name}"

    async def list_restaurants(self) -> str:
        """
        Display all available active restaurants.
        """
        restaurants = await self.restaurant_repo.list_active()
        if not restaurants:
            return "No restaurants available."
        lines = ["Available Restaurants:"]
        for idx, r in enumerate(restaurants, start=1):
            curr = " (selected)" if self.restaurant and self.restaurant.id == r.id else ""
            lines.append(f"{idx}. {r.name}{curr}")
        lines.append('\nType "restaurant <number>" to switch.')
        return "\n".join(lines)

    async def _get_active_session(self) -> Optional[CustomerSession]:
        """
        Retrieve fresh CustomerSession object if current session is active.
        """
        if not self.current_session_id:
            return None
        sess = await self.session_repo.get_by_id(self.current_session_id)
        if sess and sess.is_currently_active:
            return sess
        self.current_session_id = None
        return None

    async def handle_command(self, raw_command: str) -> str:
        """
        Main router processing interactive CLI user commands.
        """
        cmd_str = raw_command.strip()
        if not cmd_str:
            return ""

        parts = cmd_str.split()
        verb = parts[0].lower()
        args = parts[1:]

        try:
            # 1. System Commands
            if verb == "help":
                return self._render_help()

            if verb in ("exit", "quit"):
                return "EXIT"

            if verb == "reset":
                return await self._handle_reset()

            if verb == "restaurants":
                return await self.list_restaurants()

            if verb == "restaurant" and args:
                return await self.select_restaurant(args[0])

            # 2. Session Info
            if verb == "session":
                return await self._render_session_info()

            # 3. Entry Flows (QR & Tables)
            if verb == "qr":
                return await self._handle_qr_flow(args[0] if args else None)

            if verb == "tables":
                return await self._handle_tables_flow(args[0] if args else None)

            # 4. Menu Browsing
            if verb in ("menu", "categories"):
                return await self._render_menu_categories()

            if verb == "category" and args:
                return await self._render_category_items(args[0])

            # 5. Cart Operations
            if verb == "cart":
                return await self._render_cart()

            if verb == "add" and args:
                qty = int(args[1]) if len(args) > 1 and args[1].isdigit() else 1
                return await self._handle_add_item(args[0], qty)

            if verb == "qty" and len(args) >= 2:
                return await self._handle_update_quantity(args[0], int(args[1]))

            if verb == "remove" and args:
                return await self._handle_remove_item(args[0])

            if verb == "clear":
                return await self._handle_clear_cart()

            # 6. Checkout
            if verb in ("confirm", "checkout"):
                return await self._handle_checkout()

            # 7. Orders
            if verb in ("orders", "status"):
                return await self._render_orders()

            if verb == "order" and args:
                return await self._render_order_detail(args[0])

            # 8. Billing & Settlement
            if verb == "bill":
                return await self._handle_bill()

            if verb == "settle":
                return await self._handle_settle()

            # 9. Kitchen Operations
            if verb == "kitchen":
                if not args:
                    return self._render_kitchen_help()
                sub = args[0].lower()
                target_order = args[1] if len(args) > 1 else None
                return await self._handle_kitchen_command(sub, target_order)

            return f'Unknown command "{verb}". Type "help" to view available commands.'

        except AppException as app_err:
            return f"⚠️ {app_err.message}"
        except Exception as err:
            return f"⚠️ Error: {str(err)}"

    def _render_help(self) -> str:
        return (
            "==================================================\n"
            " SIMULATOR COMMANDS\n"
            "==================================================\n\n"
            "CUSTOMER COMMANDS\n"
            "  qr [number]             Simulate scanning a table QR code\n"
            "  tables [number]         Simulate direct WhatsApp table picker\n"
            "  menu                    Browse menu categories\n"
            "  categories              Browse menu categories\n"
            "  category <number>       List food items in category\n"
            "  add <item> [qty]        Add item to active cart\n"
            "  cart                    View current cart\n"
            "  qty <item> <quantity>   Update quantity of cart item\n"
            "  remove <item>           Remove item from cart\n"
            "  clear                   Clear cart\n"
            "  confirm                 Checkout active cart into an Order\n"
            "  orders                  View status of all placed orders\n"
            "  order <order_number>    View detailed items for an order\n"
            "  bill                    Request consolidated dining bill\n"
            "  session                 View current session details\n"
            "  status                  Quick order status check\n\n"
            "KITCHEN COMMANDS\n"
            "  kitchen                 View kitchen instructions\n"
            "  kitchen orders          View active kitchen queue\n"
            "  kitchen accept <order>  Move order to ACCEPTED\n"
            "  kitchen preparing <ord> Move order to PREPARING\n"
            "  kitchen ready <order>   Move order to READY\n"
            "  kitchen served <order>  Move order to SERVED\n"
            "  kitchen cancel <order>  Cancel order from allowed state\n\n"
            "SETTLEMENT & SYSTEM\n"
            "  settle                  Finalize bill and free table\n"
            "  restaurants             List available restaurants\n"
            "  restaurant <number>     Switch selected restaurant\n"
            "  reset                   Reset local simulator context\n"
            "  help                    Show this help message\n"
            "  exit                    Quit simulator"
        )

    def _render_kitchen_help(self) -> str:
        return (
            "==================================================\n"
            " KITCHEN SIMULATOR\n"
            "==================================================\n"
            "Commands:\n"
            "  kitchen orders          View active restaurant orders\n"
            "  kitchen accept <order>  Advance status: NEW -> ACCEPTED\n"
            "  kitchen preparing <ord> Advance status: ACCEPTED -> PREPARING\n"
            "  kitchen ready <order>   Advance status: PREPARING -> READY\n"
            "  kitchen served <order>  Advance status: READY -> SERVED\n"
            "  kitchen cancel <order>  Cancel order from NEW or ACCEPTED"
        )

    async def _handle_reset(self) -> str:
        self.current_session_id = None
        self.category_map.clear()
        self.item_map.clear()
        self.cart_item_map.clear()
        self.table_map.clear()
        return "Simulator session reset. Type \"qr\" or \"tables\" to begin a new session."

    async def _render_session_info(self) -> str:
        sess = await self._get_active_session()
        if not sess:
            return "No active dining session. Type \"qr\" or \"tables\" to begin."

        orders = await self.order_repo.get_orders_by_session(sess.id)
        cart = await self.cart_service.get_cart(sess.id)

        table_num = sess.table.table_number if sess.table else "Table"
        res_name = self.restaurant.name if self.restaurant else "Restaurant"

        return (
            "==================================================\n"
            " CURRENT SESSION\n"
            "==================================================\n"
            f"Restaurant: {res_name}\n"
            f"Table: {table_num}\n"
            f"Session Status: {sess.status}\n"
            f"Orders: {len(orders)}\n"
            f"Current Cart Items: {cart.item_count}"
        )

    async def _handle_qr_flow(self, choice: Optional[str] = None) -> str:
        tables = await self.table_repo.list_by_restaurant(self.restaurant.id)
        if not tables:
            return f"No active tables configured for {self.restaurant.name}."

        self.table_map = {idx: t for idx, t in enumerate(tables, start=1)}

        if not choice:
            lines = ["Available demo QR tables:"]
            for idx, t in self.table_map.items():
                lines.append(f"{idx}. {t.table_number}")
            lines.append('\nType "qr <number>" to simulate scanning a table QR code.')
            return "\n".join(lines)

        selected_table = None
        if choice.isdigit():
            selected_table = self.table_map.get(int(choice))
        else:
            for t in tables:
                if t.table_number.lower() == choice.lower() or t.qr_token == choice:
                    selected_table = t
                    break

        if not selected_table:
            return f'Invalid table selection "{choice}". Type "qr" to view available tables.'

        # Use existing SessionService QR logic
        session_resp = await self.session_service.create_or_resume_qr_session(
            customer_session_identity=self.customer_phone,
            qr_token=selected_table.qr_token,
        )
        self.current_session_id = session_resp.session_id
        await self.session.commit()

        notif_text = self._format_outbound_notifications()
        return (
            f"QR detected.\n"
            f"Restaurant: {self.restaurant.name}\n"
            f"Table: {selected_table.table_number}\n"
            f"Session created.{notif_text}\n"
            f'Type "menu" to view food categories.'
        )

    async def _handle_tables_flow(self, choice: Optional[str] = None) -> str:
        direct_resp = await self.session_service.list_active_tables_for_direct_entry(self.restaurant.id)
        tables = direct_resp.tables
        if not tables:
            return f"Currently, no dining tables are available at {self.restaurant.name}."

        raw_tables = await self.table_repo.list_by_restaurant(self.restaurant.id)
        raw_map = {t.id: t for t in raw_tables}
        self.table_map = {idx: raw_map[t.id] for idx, t in enumerate(tables, start=1) if t.id in raw_map}

        if not choice:
            lines = ["Please select your table:"]
            for idx, t in self.table_map.items():
                lines.append(f"[{idx}] {t.table_number}")
            lines.append('\nType "tables <number>" to seat at this table.')
            return "\n".join(lines)

        selected_table = None
        if choice.isdigit():
            selected_table = self.table_map.get(int(choice))

        if not selected_table:
            return f'Invalid table selection "{choice}". Type "tables" to view available options.'

        session_resp = await self.session_service.create_or_resume_direct_session(
            customer_session_identity=self.customer_phone,
            restaurant_id=self.restaurant.id,
            table_id=selected_table.id,
        )
        self.current_session_id = session_resp.session_id
        await self.session.commit()

        notif_text = self._format_outbound_notifications()
        return (
            f"Table selected.\n"
            f"Restaurant: {self.restaurant.name}\n"
            f"Table: {selected_table.table_number}\n"
            f"Session created.{notif_text}\n"
            f'Type "menu" to view food categories.'
        )

    async def _render_menu_categories(self) -> str:
        sess = await self._get_active_session()
        if not sess:
            return 'Please select a table first using "qr" or "tables".'

        categories = await self.menu_service.get_categories(sess.id)
        if not categories:
            return "No menu categories available."

        self.category_map = {idx: cat for idx, cat in enumerate(categories, start=1)}

        lines = [
            "==================================================",
            f" {self.restaurant.name} Menu",
            f" Table: {sess.table.table_number if sess.table else 'Table'}",
            "==================================================",
            "",
            "Categories:",
        ]
        for idx, cat in self.category_map.items():
            lines.append(f"{idx}. {cat.name}")

        lines.append('\nType "category <number>" to view dishes.')
        return "\n".join(lines)

    async def _render_category_items(self, cat_choice: str) -> str:
        sess = await self._get_active_session()
        if not sess:
            return 'Please select a table first using "qr" or "tables".'

        if not self.category_map:
            categories = await self.menu_service.get_categories(sess.id)
            self.category_map = {idx: cat for idx, cat in enumerate(categories, start=1)}

        selected_cat = None
        if cat_choice.isdigit():
            selected_cat = self.category_map.get(int(cat_choice))
        else:
            for cat in self.category_map.values():
                if cat.name.lower() == cat_choice.lower():
                    selected_cat = cat
                    break

        if not selected_cat:
            return f'Category "{cat_choice}" not found. Type "menu" to view categories.'

        # Eagerly load available items in this category
        items = await self.menu_service.get_category_items(sess.id, selected_cat.id)
        if not items:
            return f'No items currently available in "{selected_cat.name}".'

        self.item_map = {idx: item for idx, item in enumerate(items, start=1)}

        lines = [
            f"{selected_cat.name}",
            "",
        ]
        for idx, itm in self.item_map.items():
            lines.append(f"{idx}. {itm.name} — ₹{itm.price}")

        lines.append('\nType "add <item_number>" to add to your cart.')
        return "\n".join(lines)

    async def _handle_add_item(self, item_choice: str, quantity: int) -> str:
        sess = await self._get_active_session()
        if not sess:
            return 'Please select a table first using "qr" or "tables".'

        if quantity <= 0:
            return "Quantity must be greater than zero."

        target_item = None
        if item_choice.isdigit() and int(item_choice) in self.item_map:
            target_item = self.item_map[int(item_choice)]
        else:
            # Search by name in restaurant
            repo = MenuItemRepository(self.session)
            items = await repo.list_by_restaurant(self.restaurant.id, available_only=True)
            for itm in items:
                if itm.name.lower() == item_choice.lower() or str(itm.id) == item_choice:
                    target_item = itm
                    break

        if not target_item:
            return f'Item "{item_choice}" not found. Type "menu" or "category <number>" first.'

        cart_resp = await self.cart_service.add_item(
            session_id=sess.id,
            menu_item_id=target_item.id,
            quantity=quantity,
        )
        await self.session.commit()

        # Find updated quantity
        item_qty = sum(i.quantity for i in cart_resp.items if i.menu_item_id == target_item.id)

        return (
            f"{target_item.name} added to cart.\n"
            f"Quantity: {item_qty}\n"
            f'Type "cart" to view your cart or "confirm" to place order.'
        )

    async def _render_cart(self) -> str:
        sess = await self._get_active_session()
        if not sess:
            return 'Please select a table first using "qr" or "tables".'

        cart = await self.cart_service.get_cart(sess.id)
        if not cart.items:
            return "Your cart is empty. Type \"menu\" to browse food."

        self.cart_item_map = {idx: item for idx, item in enumerate(cart.items, start=1)}

        lines = [
            "==================================================",
            " YOUR CART",
            "==================================================",
            "",
        ]
        for idx, itm in self.cart_item_map.items():
            lines.append(f"{idx}. {itm.name} × {itm.quantity}    ₹{itm.line_total}")

        lines.extend([
            "",
            f"Subtotal: ₹{cart.subtotal}",
            "",
            'Commands: confirm, remove <item>, qty <item> <quantity>, clear',
        ])
        return "\n".join(lines)

    async def _handle_update_quantity(self, item_choice: str, new_quantity: int) -> str:
        sess = await self._get_active_session()
        if not sess:
            return "Please select a table first."

        cart = await self.cart_service.get_cart(sess.id)
        if not self.cart_item_map:
            self.cart_item_map = {idx: item for idx, item in enumerate(cart.items, start=1)}

        target_cart_item_id = None
        if item_choice.isdigit() and int(item_choice) in self.cart_item_map:
            target_cart_item_id = self.cart_item_map[int(item_choice)].id
        else:
            for itm in cart.items:
                if itm.name.lower() == item_choice.lower() or str(itm.menu_item_id) == item_choice or str(itm.id) == item_choice:
                    target_cart_item_id = itm.id
                    break

        if not target_cart_item_id:
            return f'Item "{item_choice}" not found in cart.'

        await self.cart_service.update_item_quantity(
            session_id=sess.id,
            cart_item_id=target_cart_item_id,
            quantity=new_quantity,
        )
        await self.session.commit()
        return await self._render_cart()

    async def _handle_remove_item(self, item_choice: str) -> str:
        sess = await self._get_active_session()
        if not sess:
            return "Please select a table first."

        cart = await self.cart_service.get_cart(sess.id)
        if not self.cart_item_map:
            self.cart_item_map = {idx: item for idx, item in enumerate(cart.items, start=1)}

        target_cart_item_id = None
        if item_choice.isdigit() and int(item_choice) in self.cart_item_map:
            target_cart_item_id = self.cart_item_map[int(item_choice)].id
        else:
            for itm in cart.items:
                if itm.name.lower() == item_choice.lower() or str(itm.menu_item_id) == item_choice or str(itm.id) == item_choice:
                    target_cart_item_id = itm.id
                    break

        if not target_cart_item_id:
            return f'Item "{item_choice}" not found in cart.'

        await self.cart_service.remove_item(
            session_id=sess.id,
            cart_item_id=target_cart_item_id,
        )
        await self.session.commit()
        return "Item removed from cart.\n" + (await self._render_cart())

    async def _handle_clear_cart(self) -> str:
        sess = await self._get_active_session()
        if not sess:
            return "Please select a table first."

        await self.cart_service.clear_cart(sess.id)
        await self.session.commit()
        return "Your cart has been cleared."

    async def _handle_checkout(self) -> str:
        sess = await self._get_active_session()
        if not sess:
            return "Please select a table first."

        order_resp = await self.order_service.checkout_cart(sess.id)
        await self.session.commit()

        table_name = sess.table.table_number if sess.table else "Table"
        return (
            "Creating order...\n"
            "Order created successfully.\n\n"
            f"Order: {order_resp.order_number}\n"
            f"Table: {table_name}\n"
            f"Total: ₹{order_resp.total_amount}\n"
            f"Status: {order_resp.status}\n\n"
            "The kitchen has received your order. You may order more food anytime!"
        )

    async def _render_orders(self) -> str:
        sess = await self._get_active_session()
        if not sess:
            return "Please select a table first."

        orders = await self.order_service.get_session_orders(sess.id)
        if not orders:
            return "Your orders:\nNo orders placed yet in this session."

        lines = ["Your orders:"]
        for ord_item in orders:
            lines.append(f"{ord_item.order_number} — {ord_item.status}")
        return "\n".join(lines)

    async def _render_order_detail(self, order_ref: str) -> str:
        sess = await self._get_active_session()
        if not sess:
            return "Please select a table first."

        orders = await self.order_service.get_session_orders(sess.id)
        target = None
        for o in orders:
            if o.order_number.lower() == order_ref.lower() or str(o.id) == order_ref:
                target = o
                break

        if not target:
            return f'Order "{order_ref}" not found in this dining session.'

        lines = [
            f"Order {target.order_number} — {target.status}",
            f"Table: {target.table_number}",
            "Items:",
        ]
        for itm in target.items:
            lines.append(f"  - {itm.item_name} × {itm.quantity} (₹{itm.line_total})")
        lines.append(f"Total: ₹{target.total_amount}")
        return "\n".join(lines)

    async def _handle_bill(self) -> str:
        sess = await self._get_active_session()
        if not sess:
            return "Please select a table first."

        bill_resp = await self.billing_service.generate_or_get_bill(sess.id)
        await self.session.commit()

        table_num = sess.table.table_number if sess.table else "Table"
        lines = [
            "==================================================",
            " BILL",
            "==================================================",
            f"Table: {table_num}",
            f"Bill: {bill_resp.bill_number}",
            "",
        ]
        for itm in bill_resp.items:
            lines.append(f"{itm.item_name_snapshot} × {itm.quantity}    ₹{itm.line_total}")

        lines.extend([
            "",
            f"Subtotal: ₹{bill_resp.subtotal}",
            f"Tax: ₹{bill_resp.tax_amount}",
            f"Total: ₹{bill_resp.grand_total}",
            "",
            "Please notify restaurant staff to settle your bill.",
        ])
        return "\n".join(lines)

    async def _handle_settle(self) -> str:
        sess = await self._get_active_session()
        if not sess:
            return "Please select a table first."

        # Fetch bill
        bill_resp = await self.billing_service.generate_or_get_bill(sess.id)

        # Settle
        settled_resp = await self.billing_service.settle_bill(
            bill_id=bill_resp.id,
            restaurant_id=self.restaurant.id,
            session_id=sess.id,
        )
        await self.session.commit()

        table_num = sess.table.table_number if sess.table else "Table"
        self.current_session_id = None

        return (
            f"Bill {settled_resp.bill_number} settled.\n"
            "Session closed.\n"
            f"{table_num} is now available."
        )

    async def _handle_kitchen_command(self, action: str, order_ref: Optional[str] = None) -> str:
        if action == "orders":
            k_orders = await self.order_service.get_kitchen_orders(self.restaurant.id)
            if not k_orders:
                return "Kitchen Queue: No active orders."
            lines = ["==================================================", " KITCHEN QUEUE", "=================================================="]
            for ko in k_orders:
                lines.append(f"{ko.order_number} | {ko.table_number} | {ko.status} | {ko.item_count} items (₹{ko.total_amount})")
            return "\n".join(lines)

        if not order_ref:
            return f'Please specify an order number, e.g. "kitchen {action} ORD-123456".'

        # Resolve order
        k_orders = await self.order_service.get_kitchen_orders(self.restaurant.id)
        target = None
        if order_ref.isdigit() and 1 <= int(order_ref) <= len(k_orders):
            target = k_orders[int(order_ref) - 1]
        else:
            for ko in k_orders:
                if ko.order_number.lower() == order_ref.lower() or str(ko.id) == order_ref:
                    target = ko
                    break

        if not target:
            # Try fetching by order number directly across restaurant orders
            stmt = select(Order).where(
                Order.restaurant_id == self.restaurant.id,
                Order.order_number == order_ref.upper(),
            )
            res = await self.session.execute(stmt)
            ord_entity = res.scalars().first()
            if ord_entity:
                target = ord_entity

        if not target:
            return f'Order "{order_ref}" not found in kitchen queue for {self.restaurant.name}.'

        status_map = {
            "accept": OrderStatus.ACCEPTED.value,
            "preparing": OrderStatus.PREPARING.value,
            "ready": OrderStatus.READY.value,
            "served": OrderStatus.SERVED.value,
            "cancel": OrderStatus.CANCELLED.value,
        }
        target_status = status_map.get(action)
        if not target_status:
            return f'Unknown kitchen action "{action}". Allowed: accept, preparing, ready, served, cancel.'

        # 1. Advance state machine
        updated = await self.order_service.transition_order_status(
            restaurant_id=self.restaurant.id,
            order_id=target.id,
            new_status=target_status,
        )
        await self.session.commit()

        # 2. Trigger outbound notification post-commit
        await self.notification_service.send_kitchen_status_notification(
            restaurant_id=self.restaurant.id,
            order_id=target.id,
            new_status=target_status,
        )

        notif_block = self._format_outbound_notifications()
        return (
            f"Kitchen status updated:\n"
            f"{updated.status}"
            f"{notif_block}"
        )


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    except Exception:
        pass


async def ensure_seed_data(session: AsyncSession) -> None:
    """
    Ensure the demo restaurant 'SpiceBox' exists with tables, categories, and dishes.
    """
    stmt = select(Restaurant).where(Restaurant.name == "SpiceBox")
    existing_res = (await session.execute(stmt)).scalars().first()
    if existing_res:
        return

    res = Restaurant(
        name="SpiceBox",
        description="Authentic Indian dining experience featuring slow-cooked biryanis and coastal delicacies.",
        phone_number="+919876543210",
        address="42 Culinary Avenue, Indiranagar, Bengaluru",
        is_active=True,
    )
    session.add(res)
    await session.flush()

    for i in range(1, 6):
        tbl = RestaurantTable(
            restaurant_id=res.id,
            table_number=f"Table {i}",
            qr_token=generate_qr_token(),
            is_active=True,
        )
        session.add(tbl)
    await session.flush()

    categories_data = [
        ("Starters", "Crispy and spicy appetizers to begin your feast", 1),
        ("Main Course", "Traditional curries and breads", 2),
        ("Biryani", "Dum-cooked fragrant basmati rice delicacies", 3),
        ("Drinks", "Chilled refreshments and coolers", 4),
        ("Desserts", "Sweet concluding treats", 5),
    ]
    category_map = {}
    for name, desc, order in categories_data:
        cat = MenuCategory(
            restaurant_id=res.id,
            name=name,
            description=desc,
            display_order=order,
            is_active=True,
        )
        session.add(cat)
        category_map[name] = cat
    await session.flush()

    menu_items_data = [
        ("Starters", "Chicken 65", "Crispy deep-fried chicken tossed in fiery curry leaf chili tempering", Decimal("240.00"), 1),
        ("Starters", "Paneer 65", "Spiced golden fried cottage cheese cubes garnished with coriander", Decimal("200.00"), 2),
        ("Biryani", "Chicken Biryani", "Aromatic long-grain basmati dum biryani with marinated tender chicken", Decimal("280.00"), 1),
        ("Biryani", "Mutton Biryani", "Slow-cooked succulent mutton pieces layered with saffron spiced rice", Decimal("360.00"), 2),
        ("Biryani", "Veg Biryani", "Seasonal farm vegetables simmered in fragrant whole spices and herbs", Decimal("220.00"), 3),
        ("Drinks", "Coke", "Classic chilled carbonated soda 330ml can", Decimal("40.00"), 1),
        ("Drinks", "Fresh Lime", "Refreshing freshly squeezed lime juice with mint and club soda", Decimal("60.00"), 2),
        ("Desserts", "Gulab Jamun", "Warm golden milk-solid dumplings soaked in rose and cardamom sugar syrup", Decimal("90.00"), 1),
    ]
    for cat_name, name, desc, price, order in menu_items_data:
        cat = category_map[cat_name]
        item = MenuItem(
            restaurant_id=res.id,
            category_id=cat.id,
            name=name,
            description=desc,
            price=price,
            is_available=True,
            display_order=order,
        )
        session.add(item)
    await session.commit()


async def run_interactive():
    """
    Start the interactive CLI simulator loop.
    Supports PostgreSQL and automatic fallback to local SQLite (dev_simulator.db).
    """
    parser = argparse.ArgumentParser(description="WhatsApp Dine-In Ordering CLI Simulator")
    parser.add_argument("--db", default=None, help="Custom database connection URL")
    parser.add_argument("--sqlite", action="store_true", help="Force local SQLite database mode")
    parser.add_argument("--phone", default=None, help="Customer phone number (default: +919999888877)")
    args = parser.parse_args()

    session_maker = None
    if args.sqlite or (args.db and "sqlite" in args.db):
        db_url = args.db or "sqlite+aiosqlite:///dev_simulator.db"
        engine = create_async_engine(db_url, echo=False)
        async with engine.begin() as conn:
            await conn.execute(text("PRAGMA foreign_keys=ON"))
            await conn.run_sync(Base.metadata.create_all)
        session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    elif args.db:
        engine = create_async_engine(args.db, echo=False)
        session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    else:
        # Try configured database (Postgres) first, fallback to SQLite if connection fails
        try:
            async with async_session_factory() as test_sess:
                await test_sess.execute(text("SELECT 1"))
            session_maker = async_session_factory
        except Exception:
            print("Notice: PostgreSQL server not reachable locally. Falling back to local SQLite database (dev_simulator.db)...")
            db_url = "sqlite+aiosqlite:///dev_simulator.db"
            engine = create_async_engine(db_url, echo=False)
            async with engine.begin() as conn:
                await conn.execute(text("PRAGMA foreign_keys=ON"))
                await conn.run_sync(Base.metadata.create_all)
            session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)

    async with session_maker() as session:
        await ensure_seed_data(session)
        simulator = WhatsAppSimulator(session, customer_phone=args.phone)
        banner = await simulator.initialize()
        print(banner)

        while True:
            try:
                user_input = input("\n> ").strip()
                if not user_input:
                    continue

                response = await simulator.handle_command(user_input)
                if response == "EXIT":
                    print("Exiting simulator. Thank you for dining with us!")
                    break

                if response:
                    print(f"\n{response}")

            except (KeyboardInterrupt, EOFError):
                print("\nExiting simulator. Goodbye!")
                break
            except Exception as e:
                print(f"\n⚠️ Unexpected error: {e}")


if __name__ == "__main__":
    asyncio.run(run_interactive())
