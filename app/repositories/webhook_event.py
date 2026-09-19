from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.webhook_event import WebhookEvent
from app.repositories.base import BaseRepository


class WebhookEventRepository(BaseRepository[WebhookEvent]):
    """
    Data access repository for persistent inbound WhatsApp webhook event deduplication.
    """
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(WebhookEvent, session)

    async def get_by_message_id(self, message_id: str) -> Optional[WebhookEvent]:
        """
        Lookup an inbound webhook event by its WhatsApp message ID.
        """
        stmt = (
            select(WebhookEvent)
            .where(WebhookEvent.message_id == message_id)
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def record_event(
        self,
        message_id: str,
        from_phone_masked: str,
        event_type: str,
    ) -> WebhookEvent:
        """
        Persist a newly received inbound webhook message event.
        """
        event = WebhookEvent(
            message_id=message_id,
            from_phone_masked=from_phone_masked,
            event_type=event_type,
        )
        self.session.add(event)
        await self.session.flush()
        return event
