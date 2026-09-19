from decimal import Decimal
from typing import List, Optional
from uuid import UUID
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cart import Cart, CartItem
from app.repositories.base import BaseRepository


class CartRepository(BaseRepository[Cart]):
    """
    Repository for Cart domain entities.
    """
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Cart, session)

    async def get_active_cart_for_session(
        self, session_id: UUID, for_update: bool = False
    ) -> Optional[Cart]:
        """
        Retrieve active cart for a customer session with fresh populate_existing.
        Optionally acquires a row lock (FOR UPDATE) in concurrent environments.
        """
        stmt = (
            select(Cart)
            .where(Cart.customer_session_id == session_id, Cart.status == "ACTIVE")
            .execution_options(populate_existing=True)
        )
        if for_update and self.session.bind and getattr(self.session.bind.dialect, "name", "") != "sqlite":
            stmt = stmt.with_for_update()

        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_or_create_active_cart(self, session_id: UUID) -> Cart:
        """
        Get active cart for session, or initialize a new active cart.
        """
        cart = await self.get_active_cart_for_session(session_id)
        if not cart:
            cart = Cart(customer_session_id=session_id, status="ACTIVE")
            self.session.add(cart)
            await self.session.flush()
            cart = await self.get_active_cart_for_session(session_id)
        return cart  # type: ignore[return-value]


class CartItemRepository(BaseRepository[CartItem]):
    """
    Repository for CartItem line items.
    """
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(CartItem, session)

    async def get_by_cart_and_menu_item(
        self, cart_id: UUID, menu_item_id: UUID
    ) -> Optional[CartItem]:
        """
        Lookup cart item for a specific menu item within a cart.
        """
        stmt = (
            select(CartItem)
            .where(CartItem.cart_id == cart_id, CartItem.menu_item_id == menu_item_id)
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def add_or_increment(
        self,
        cart_id: UUID,
        menu_item_id: UUID,
        quantity: int,
        unit_price: Decimal,
    ) -> CartItem:
        """
        Add new CartItem with snapshotted unit_price or increment existing quantity.
        """
        item = await self.get_by_cart_and_menu_item(cart_id, menu_item_id)
        if item:
            item.quantity += quantity
        else:
            item = CartItem(
                cart_id=cart_id,
                menu_item_id=menu_item_id,
                quantity=quantity,
                unit_price=unit_price,
            )
            self.session.add(item)

        await self.session.flush()
        return item

    async def clear_cart_items(self, cart: Cart) -> None:
        """
        Remove all items from a cart while preserving the parent Cart record.
        """
        for item in list(cart.items):
            await self.session.delete(item)
        await self.session.flush()
