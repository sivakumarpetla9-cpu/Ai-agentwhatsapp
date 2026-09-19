from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import Customer, CustomerSession
from app.repositories.base import BaseRepository


class CustomerRepository(BaseRepository[Customer]):
    """
    Repository for Customer entity access.
    """
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Customer, session)

    async def get_by_whatsapp_id(self, whatsapp_customer_id: str) -> Optional[Customer]:
        """
        Lookup internal customer by their WhatsApp identifier.
        """
        stmt = select(Customer).where(Customer.whatsapp_customer_id == whatsapp_customer_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_or_create(
        self, whatsapp_customer_id: str, display_name: Optional[str] = None
    ) -> Customer:
        """
        Find existing customer by WhatsApp identifier or create a new one.
        """
        customer = await self.get_by_whatsapp_id(whatsapp_customer_id)
        if not customer:
            customer = Customer(
                whatsapp_customer_id=whatsapp_customer_id,
                display_name=display_name,
            )
            self.session.add(customer)
            await self.session.flush()
            await self.session.refresh(customer)
        return customer


class CustomerSessionRepository(BaseRepository[CustomerSession]):
    """
    Repository for customer dining sessions.
    """
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(CustomerSession, session)

    async def get_active_session_for_customer(
        self, customer_id: UUID
    ) -> Optional[CustomerSession]:
        """
        Find the current ACTIVE session for a customer that has not expired.
        """
        now = datetime.now(timezone.utc)
        stmt = (
            select(CustomerSession)
            .where(
                CustomerSession.customer_id == customer_id,
                CustomerSession.status == "ACTIVE",
            )
            .order_by(CustomerSession.created_at.desc())
        )
        result = await self.session.execute(stmt)
        sessions = result.scalars().all()

        for sess in sessions:
            if sess.is_currently_active:
                return sess
            else:
                # Mark as expired if timestamp passed
                sess.status = "EXPIRED"
        await self.session.flush()
        return None

    async def expire_active_sessions_for_customer(self, customer_id: UUID) -> None:
        """
        Expire all active sessions for a customer (e.g. when moving to a new table/restaurant).
        """
        stmt = (
            update(CustomerSession)
            .where(
                CustomerSession.customer_id == customer_id,
                CustomerSession.status == "ACTIVE",
            )
            .values(status="EXPIRED")
        )
        await self.session.execute(stmt)
        await self.session.flush()
