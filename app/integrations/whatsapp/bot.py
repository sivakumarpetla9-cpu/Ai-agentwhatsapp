import logging
from typing import List, Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.integrations.whatsapp.client import WhatsAppClient, whatsapp_client
from app.integrations.whatsapp.schemas import WhatsAppInboundMessage
from app.models.customer import CustomerSession
from app.models.restaurant import Restaurant
from app.repositories.customer import CustomerRepository, CustomerSessionRepository
from app.repositories.restaurant import RestaurantRepository, RestaurantTableRepository
from app.services.billing import BillingService
from app.services.cart import CartService
from app.services.customer_menu import CustomerMenuService
from app.services.order import OrderService
from app.services.session import SessionService, mask_identifier

logger = logging.getLogger("whatsapp_ordering.integrations.whatsapp.bot")
settings = get_settings()


class WhatsAppBotEngine:
    """
    Conversational router translating WhatsApp customer interactions
    (QR scans, Table Picker, Menu browsing, Cart actions, and Checkout)
    into backend domain service calls.
    """
    def __init__(
        self,
        session: AsyncSession,
        client: Optional[WhatsAppClient] = None,
    ) -> None:
        self.session = session
        self.client = client or whatsapp_client
        self.session_service = SessionService(session)
        self.menu_service = CustomerMenuService(session)
        self.cart_service = CartService(session)
        self.order_service = OrderService(session)
        self.billing_service = BillingService(session)
        self.restaurant_repo = RestaurantRepository(session)
        self.table_repo = RestaurantTableRepository(session)
        self.customer_repo = CustomerRepository(session)
        self.session_repo = CustomerSessionRepository(session)

    async def _get_default_restaurant(self) -> Optional[Restaurant]:
        """
        Identify active restaurant for direct WhatsApp table selection (Flow B).
        """
        if settings.DEFAULT_RESTAURANT_ID:
            res = await self.restaurant_repo.get_by_id(UUID(settings.DEFAULT_RESTAURANT_ID))
            if res and res.is_active:
                return res

        stmt = select(Restaurant).where(Restaurant.is_active.is_(True)).limit(1)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def _get_active_session_for_phone(self, from_phone: str) -> Optional[CustomerSession]:
        """
        Lookup active unexpired dining session for the customer.
        """
        customer = await self.customer_repo.get_by_whatsapp_id(from_phone)
        if not customer:
            return None
        return await self.session_repo.get_active_session_for_customer(customer.id)

    async def handle_inbound_message(
        self,
        from_phone: str,
        message: WhatsAppInboundMessage,
        display_name: Optional[str] = None,
    ) -> None:
        """
        Main entry point routing inbound WhatsApp messages to appropriate handlers.
        """
        masked_phone = mask_identifier(from_phone)
        logger.info(f"Processing inbound WhatsApp message from {masked_phone} (type: {message.type})")

        try:
            # 1. Check for interactive reply (button or list selection)
            if message.type == "interactive" and message.interactive:
                reply_id = ""
                if message.interactive.button_reply:
                    reply_id = message.interactive.button_reply.id
                elif message.interactive.list_reply:
                    reply_id = message.interactive.list_reply.id

                await self._handle_interactive_callback(from_phone, reply_id, display_name)
                return

            # 2. Check for text message
            if message.text:
                body = message.text.body.strip()
                await self._handle_text_message(from_phone, body, display_name)
                return

            # Unhandled message type fallback
            await self.client.send_text(
                to=from_phone,
                text="Please send a text message or select one of the interactive options to proceed.",
            )

        except AppException as app_err:
            logger.warning(f"Business logic error in WhatsApp bot: {app_err.message}")
            await self.client.send_text(to=from_phone, text=f"⚠️ {app_err.message}")
        except Exception as err:
            logger.error(f"Unexpected error in WhatsApp bot engine: {err}", exc_info=True)
            await self.client.send_text(
                to=from_phone,
                text="⚠️ An unexpected error occurred. Please try again or ask our staff for assistance.",
            )

    async def _handle_text_message(
        self, from_phone: str, body: str, display_name: Optional[str] = None
    ) -> None:
        """
        Handle incoming text messages:
        - Flow A: QR token scan (e.g. 'START <qr_token>' or raw token)
        - Commands: 'menu', 'cart', 'checkout', 'status'
        - Flow B: Direct number entry (greeting -> interactive table list)
        """
        body_lower = body.lower()

        # Check if text is a QR token (Flow A: "START qr-token" or recognized QR token)
        qr_token_candidate = None
        if body.upper().startswith("START ") or body.upper().startswith("QR "):
            parts = body.split(maxsplit=1)
            if len(parts) > 1:
                qr_token_candidate = parts[1].strip()
        elif len(body) >= 6 and not any(body_lower.startswith(cmd) for cmd in ["hi", "hello", "menu", "cart", "order", "status", "checkout", "help", "clear", "bill"]):
            # Check if this token matches a table
            table = await self.table_repo.get_by_qr_token(body)
            if table:
                qr_token_candidate = body

        if qr_token_candidate:
            await self._handle_qr_entry(from_phone, qr_token_candidate, display_name)
            return

        # Check for active session
        active_session = await self._get_active_session_for_phone(from_phone)

        # If user has an active session, support quick text commands
        if active_session:
            if "bill" in body_lower or "check" in body_lower:
                await self._handle_bill_request(from_phone, active_session)
                return
            if "cart" in body_lower:
                await self._send_cart_summary(from_phone, active_session)
                return
            if "checkout" in body_lower or "pay" in body_lower or "confirm" in body_lower:
                await self._execute_checkout(from_phone, active_session)
                return
            if "status" in body_lower or "order" in body_lower:
                await self._send_order_status(from_phone, active_session)
                return
            if "menu" in body_lower:
                await self._send_menu_categories(from_phone, active_session)
                return

            # Default active session menu response
            table_name = active_session.table.table_number if active_session.table else "your table"
            restaurant_name = active_session.restaurant.name if active_session.restaurant else "the restaurant"
            await self.client.send_buttons(
                to=from_phone,
                text=(
                    f"👋 Welcome back! You are dining at *{restaurant_name}* ({table_name}).\n"
                    "What would you like to do?"
                ),
                buttons=[
                    {"id": "VIEW_MENU", "title": "📖 Browse Menu"},
                    {"id": "VIEW_CART", "title": "🛒 View Cart"},
                    {"id": "ORDER_STATUS", "title": "🔍 Order Status"},
                ],
            )
            return

        # Flow B: Direct number entry (No active session yet)
        if "bill" in body_lower or "check" in body_lower:
            await self.client.send_text(
                to=from_phone,
                text="⚠️ You do not have an active dining session. Please select your table below to begin:",
            )

        await self._initiate_direct_table_selection(from_phone)

    async def _handle_qr_entry(
        self, from_phone: str, qr_token: str, display_name: Optional[str] = None
    ) -> None:
        """
        Flow A: Customer scanned table QR code.
        """
        session_resp = await self.session_service.create_or_resume_qr_session(
            customer_session_identity=from_phone,
            qr_token=qr_token,
        )

        customer = await self.customer_repo.get_by_whatsapp_id(from_phone)
        active_session = await self.session_repo.get_active_session_for_customer(customer.id)  # type: ignore[union-attr]

        if active_session:
            await self._send_welcome_and_menu(from_phone, active_session)

    async def _initiate_direct_table_selection(self, from_phone: str) -> None:
        """
        Flow B: Send interactive table selection list to customer.
        """
        restaurant = await self._get_default_restaurant()
        if not restaurant:
            await self.client.send_text(
                to=from_phone,
                text="⚠️ Sorry, no restaurant is currently accepting orders. Please try again later.",
            )
            return

        tables = await self.session_service.list_active_tables_for_direct_entry(restaurant.id)
        if not tables.tables:
            await self.client.send_text(
                to=from_phone,
                text=f"Welcome to *{restaurant.name}*! Currently, no dining tables are available.",
            )
            return

        # Build interactive list sections for tables
        rows = [
            {
                "id": f"SELECT_TABLE:{table.id}",
                "title": table.table_number[:24],
                "description": "Tap to seat at this table",
            }
            for table in tables.tables[:10]  # WhatsApp list limit: up to 10 rows per section
        ]

        await self.client.send_list(
            to=from_phone,
            text=f"Welcome to *{restaurant.name}*! 🍽️\nPlease select your dining table to start ordering:",
            button_label="Select Table",
            sections=[{"title": "Available Tables", "rows": rows}],
        )

    async def _handle_interactive_callback(
        self, from_phone: str, callback_id: str, display_name: Optional[str] = None
    ) -> None:
        """
        Process interactive button and list selection callbacks.
        """
        # 1. Flow B Table Selection: SELECT_TABLE:<table_id>
        if callback_id.startswith("SELECT_TABLE:"):
            table_id_str = callback_id.split(":", 1)[1]
            restaurant = await self._get_default_restaurant()
            if not restaurant:
                await self.client.send_text(to=from_phone, text="Restaurant not found.")
                return

            await self.session_service.create_or_resume_direct_session(
                customer_session_identity=from_phone,
                restaurant_id=restaurant.id,
                table_id=UUID(table_id_str),
            )
            active_session = await self._get_active_session_for_phone(from_phone)
            if active_session:
                await self._send_welcome_and_menu(from_phone, active_session)
            return

        # Ensure active session exists for all subsequent actions
        active_session = await self._get_active_session_for_phone(from_phone)
        if not active_session:
            await self.client.send_text(
                to=from_phone,
                text="⚠️ Your session has ended or is not found. Please select a table to begin.",
            )
            await self._initiate_direct_table_selection(from_phone)
            return

        # 2. View Menu Categories: VIEW_MENU
        if callback_id == "VIEW_MENU":
            await self._send_menu_categories(from_phone, active_session)
            return

        # 3. View Specific Category: VIEW_CAT:<category_id>
        if callback_id.startswith("VIEW_CAT:"):
            cat_id = UUID(callback_id.split(":", 1)[1])
            await self._send_category_items(from_phone, active_session, cat_id)
            return

        # 4. Add Item to Cart: ADD_ITEM:<item_id>:<qty>
        if callback_id.startswith("ADD_ITEM:"):
            parts = callback_id.split(":")
            item_id = UUID(parts[1])
            qty = int(parts[2]) if len(parts) > 2 else 1
            await self._add_item_to_cart(from_phone, active_session, item_id, qty)
            return

        # 5. View Cart: VIEW_CART
        if callback_id == "VIEW_CART":
            await self._send_cart_summary(from_phone, active_session)
            return

        # 6. Clear Cart: CLEAR_CART
        if callback_id == "CLEAR_CART":
            await self.cart_service.clear_cart(active_session.id)
            await self.client.send_buttons(
                to=from_phone,
                text="🗑️ Your shopping cart has been cleared.",
                buttons=[{"id": "VIEW_MENU", "title": "📖 Browse Menu"}],
            )
            return

        # 7. Checkout: CHECKOUT
        if callback_id == "CHECKOUT":
            await self._execute_checkout(from_phone, active_session)
            return

        # 8. Order Status: ORDER_STATUS or VIEW_ORDER
        if callback_id in ("ORDER_STATUS", "VIEW_ORDER"):
            await self._send_order_status(from_phone, active_session)
            return

        # 9. Request Bill: REQUEST_BILL or VIEW_BILL
        if callback_id in ("REQUEST_BILL", "VIEW_BILL"):
            await self._handle_bill_request(from_phone, active_session)
            return

        # Fallback
        await self.client.send_buttons(
            to=from_phone,
            text="How can we help you?",
            buttons=[
                {"id": "VIEW_MENU", "title": "📖 Browse Menu"},
                {"id": "VIEW_CART", "title": "🛒 View Cart"},
            ],
        )

    async def _send_welcome_and_menu(
        self, from_phone: str, active_session: CustomerSession
    ) -> None:
        """
        Welcome customer at confirmed table and present menu categories.
        """
        restaurant_name = active_session.restaurant.name if active_session.restaurant else "Restaurant"
        table_name = active_session.table.table_number if active_session.table else "your table"

        welcome_text = (
            f"🎉 Welcome to *{restaurant_name}*!\n"
            f"You are seated at *{table_name}*.\n\n"
            "Browse our menu below to add food to your cart:"
        )
        await self._send_menu_categories(from_phone, active_session, prefix_text=welcome_text)

    async def _send_menu_categories(
        self,
        from_phone: str,
        active_session: CustomerSession,
        prefix_text: Optional[str] = None,
    ) -> None:
        """
        Send list of active menu categories to customer.
        """
        categories = await self.menu_service.get_categories(active_session.id)
        if not categories:
            await self.client.send_text(
                to=from_phone, text="The menu is currently being updated. Please check back shortly!"
            )
            return

        rows = [
            {
                "id": f"VIEW_CAT:{cat.id}",
                "title": cat.name[:24],
                "description": cat.description[:72] if cat.description else "View delicious dishes",
            }
            for cat in categories[:10]
        ]

        text = prefix_text or "📖 *Menu Categories*\nSelect a category to view dishes:"
        await self.client.send_list(
            to=from_phone,
            text=text,
            button_label="View Categories",
            sections=[{"title": "Categories", "rows": rows}],
        )

    async def _send_category_items(
        self, from_phone: str, active_session: CustomerSession, category_id: UUID
    ) -> None:
        """
        Send available items in selected category.
        """
        items = await self.menu_service.get_category_items(
            active_session.id, category_id
        )
        if not items:
            await self.client.send_buttons(
                to=from_phone,
                text="No items currently available in this category.",
                buttons=[{"id": "VIEW_MENU", "title": "« Back to Categories"}],
            )
            return

        rows = [
            {
                "id": f"ADD_ITEM:{item.id}:1",
                "title": f"Add {item.name}"[:24],
                "description": f"₹{item.price:.2f}" + (f" - {item.description[:40]}" if item.description else ""),
            }
            for item in items[:9]
        ]
        # Back option
        rows.append({"id": "VIEW_MENU", "title": "« Back to Categories", "description": "Browse other sections"})

        await self.client.send_list(
            to=from_phone,
            text=f"Select an item to add to your table cart:",
            button_label="Select Dish",
            sections=[{"title": "Dishes", "rows": rows}],
        )

    async def _add_item_to_cart(
        self,
        from_phone: str,
        active_session: CustomerSession,
        menu_item_id: UUID,
        quantity: int,
    ) -> None:
        """
        Add item to active cart and send confirmation with subtotal.
        """
        cart = await self.cart_service.add_item(
            session_id=active_session.id,
            menu_item_id=menu_item_id,
            quantity=quantity,
        )

        # Find added item name
        item_name = "Item"
        for item in cart.items:
            if item.menu_item_id == menu_item_id:
                item_name = item.name
                break

        confirmation_text = (
            f"✅ Added *{item_name}* (x{quantity}) to cart!\n\n"
            f"🛒 *Cart Subtotal*: *₹{cart.subtotal}* ({cart.item_count} items)"
        )
        await self.client.send_buttons(
            to=from_phone,
            text=confirmation_text,
            buttons=[
                {"id": "VIEW_CART", "title": "🛒 View Cart"},
                {"id": "VIEW_MENU", "title": "➕ Add More"},
                {"id": "CHECKOUT", "title": "⚡ Checkout"},
            ],
        )

    async def _send_cart_summary(
        self, from_phone: str, active_session: CustomerSession
    ) -> None:
        """
        Send itemized cart breakdown with line totals and subtotal.
        """
        cart = await self.cart_service.get_cart(active_session.id)
        table_name = active_session.table.table_number if active_session.table else "your table"

        if not cart.items:
            await self.client.send_buttons(
                to=from_phone,
                text=f"🛒 Your cart for *{table_name}* is currently empty.",
                buttons=[{"id": "VIEW_MENU", "title": "📖 Browse Menu"}],
            )
            return

        lines = [f"🛒 *Your Table Cart* ({table_name}):\n"]
        for itm in cart.items:
            lines.append(f"• *{itm.name}* x{itm.quantity} — ₹{itm.line_total}")

        lines.append(f"\n*Subtotal*: *₹{cart.subtotal}* ({cart.item_count} items)")
        lines.append("_Prices include all applicable taxes._")

        cart_text = "\n".join(lines)
        await self.client.send_buttons(
            to=from_phone,
            text=cart_text,
            buttons=[
                {"id": "CHECKOUT", "title": "✅ Confirm Order"},
                {"id": "VIEW_MENU", "title": "➕ Add More Items"},
                {"id": "CLEAR_CART", "title": "🗑 Clear Cart"},
            ],
        )

    async def _execute_checkout(
        self, from_phone: str, active_session: CustomerSession
    ) -> None:
        """
        Convert active cart into a confirmed placed Order in NEW status.
        """
        order = await self.order_service.checkout_cart(session_id=active_session.id)
        table_name = active_session.table.table_number if active_session.table else "your table"

        order_text = (
            f"🎉 *Order #{order.order_number} Confirmed!*\n\n"
            f"📍 *Table*: {table_name}\n"
            f"🍲 *Status*: *NEW* (Received in Kitchen)\n"
            f"💰 *Total*: ₹{order.total_amount}\n\n"
            "Our kitchen has received your order and is starting preparation. "
            "You will be notified as it progresses!"
        )
        await self.client.send_buttons(
            to=from_phone,
            text=order_text,
            buttons=[
                {"id": "ORDER_STATUS", "title": "🔍 Order Status"},
                {"id": "VIEW_MENU", "title": "📖 Order More Food"},
            ],
        )

    async def _send_order_status(
        self, from_phone: str, active_session: CustomerSession
    ) -> None:
        """
        Send current status of all orders placed during the session.
        """
        orders = await self.order_service.get_session_orders(active_session.id)
        table_name = active_session.table.table_number if active_session.table else "your table"

        if not orders:
            await self.client.send_buttons(
                to=from_phone,
                text=f"No orders placed yet for *{table_name}*.",
                buttons=[{"id": "VIEW_MENU", "title": "📖 Browse Menu"}],
            )
            return

        lines = [f"📋 *Order Status for {table_name}*:\n"]
        for ord_item in orders:
            status_emoji = {
                "NEW": "🆕",
                "ACCEPTED": "👨‍🍳",
                "PREPARING": "🔥",
                "READY": "🔔",
                "SERVED": "✅",
                "CANCELLED": "❌",
            }.get(ord_item.status, "ℹ️")

            lines.append(
                f"{status_emoji} *Order #{ord_item.order_number}*: *{ord_item.status}* "
                f"({ord_item.item_count} items, ₹{ord_item.total_amount})"
            )

        lines.append("\n_Status updates automatically as your food is prepared._")
        status_text = "\n".join(lines)

        buttons = [
            {"id": "ORDER_STATUS", "title": "🔄 Refresh Status"},
            {"id": "VIEW_MENU", "title": "📖 Order More Food"},
        ]
        if any(ord_item.status == "SERVED" for ord_item in orders):
            buttons.append({"id": "REQUEST_BILL", "title": "🧾 Request Bill"})

        await self.client.send_buttons(
            to=from_phone,
            text=status_text,
            buttons=buttons,
        )

    async def _handle_bill_request(
        self, from_phone: str, active_session: CustomerSession
    ) -> None:
        """
        Handle customer bill request (text 'BILL' or button 'REQUEST_BILL').
        Idempotently generates or fetches OPEN consolidated bill for the session.
        Never marks session CLOSED.
        """
        table_name = active_session.table.table_number if active_session.table else "your table"

        try:
            bill = await self.billing_service.generate_or_get_bill(active_session.id)
        except AppException as err:
            if getattr(err, "error_code", None) == "NO_BILLABLE_ORDERS":
                await self.client.send_buttons(
                    to=from_phone,
                    text=(
                        f"⚠️ No served orders found yet for *{table_name}* to generate a bill.\n\n"
                        "If you recently placed an order, please wait for it to be served or check order status."
                    ),
                    buttons=[
                        {"id": "ORDER_STATUS", "title": "🔍 Order Status"},
                        {"id": "VIEW_MENU", "title": "📖 Browse Menu"},
                    ],
                )
                return
            raise

        lines = [
            f"Table: {table_name}",
            f"Bill: {bill.bill_number}\n",
        ]

        for item in bill.items:
            lines.append(f"{item.item_name_snapshot} × {item.quantity}    ₹{item.line_total}")

        lines.append(f"\nSubtotal: ₹{bill.subtotal}")
        lines.append(f"Tax: ₹{bill.tax_amount}")
        lines.append(f"Total: ₹{bill.grand_total}")
        lines.append("\n_Thank you for dining with us! Please notify staff to settle your bill._")

        bill_text = "\n".join(lines)

        await self.client.send_buttons(
            to=from_phone,
            text=bill_text,
            buttons=[
                {"id": "ORDER_STATUS", "title": "🔍 Order Status"},
                {"id": "VIEW_MENU", "title": "📖 Order More"},
            ],
        )
