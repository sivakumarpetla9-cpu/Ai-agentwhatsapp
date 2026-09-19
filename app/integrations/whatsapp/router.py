import hashlib
import hmac
import logging
import secrets
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.database.session import get_db
from app.integrations.whatsapp.bot import WhatsAppBotEngine
from app.integrations.whatsapp.schemas import WhatsAppWebhookPayload
from app.repositories.webhook_event import WebhookEventRepository
from app.services.session import mask_identifier

logger = logging.getLogger("whatsapp_ordering.integrations.whatsapp.router")
settings = get_settings()

router = APIRouter()


def verify_meta_signature(raw_body: bytes, signature_header: Optional[str]) -> bool:
    """
    Validate HMAC-SHA256 signature from Meta WhatsApp Cloud API.
    Uses constant-time comparison to prevent timing attacks.
    """
    app_secret = settings.WHATSAPP_APP_SECRET
    if not app_secret:
        return True

    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected_signature = "sha256=" + hmac.new(
        app_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    return secrets.compare_digest(expected_signature, signature_header)


@router.get(
    "/webhook",
    status_code=status.HTTP_200_OK,
    summary="Meta Webhook Verification",
    description="Validates webhook subscription challenge with Meta WhatsApp Cloud API.",
)
async def verify_webhook(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
) -> Response:
    """
    Handle Meta WhatsApp Webhook subscription verification handshake.
    Uses timing-safe comparison for verify token.
    """
    valid_mode = hub_mode == "subscribe"
    valid_token = secrets.compare_digest(
        hub_verify_token or "", settings.WHATSAPP_VERIFY_TOKEN
    )

    if valid_mode and valid_token:
        logger.info("WhatsApp webhook challenge verified successfully.")
        return Response(
            content=hub_challenge or "",
            media_type="text/plain",
            status_code=status.HTTP_200_OK,
        )

    logger.warning("WhatsApp webhook challenge verification failed: Token mismatch or invalid mode.")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Verification token mismatch or invalid mode.",
    )


@router.post(
    "/webhook",
    status_code=status.HTTP_200_OK,
    summary="Meta Inbound Event Webhook",
    description="Receives customer WhatsApp messages and dispatches to WhatsAppBotEngine.",
)
async def process_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
    db_session: AsyncSession = Depends(get_db),
) -> dict:
    """
    Process incoming WhatsApp Cloud API messages and events.
    Enforces HMAC-SHA256 signature verification and persistent message deduplication.
    Always returns HTTP 200 to acknowledge receipt to Meta upon successful dispatch.
    """
    raw_body = await request.body()

    # 1. Enforce Meta webhook HMAC signature verification when configured or in production
    should_verify = (
        settings.WHATSAPP_WEBHOOK_VERIFY_SIGNATURE
        or settings.ENVIRONMENT.lower() == "production"
        or bool(settings.WHATSAPP_APP_SECRET)
    )

    if should_verify:
        if not verify_meta_signature(raw_body, x_hub_signature_256):
            logger.warning("WhatsApp webhook signature verification failed: Invalid or missing signature.")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid webhook signature.",
            )

    # 2. Parse and validate JSON payload
    try:
        payload = WhatsAppWebhookPayload.model_validate_json(raw_body)
    except Exception as parse_err:
        logger.warning(f"Malformed WhatsApp webhook payload rejected: {parse_err}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed webhook payload.",
        )

    # 3. Dispatch to Bot Engine with persistent event deduplication
    engine = WhatsAppBotEngine(session=db_session)
    event_repo = WebhookEventRepository(db_session)

    for entry in payload.entry:
        for change in entry.changes:
            val = change.value
            if not val or not val.messages:
                continue

            # Extract customer profile name if provided by Meta
            profile_name = None
            if val.contacts and val.contacts[0].profile:
                profile_name = val.contacts[0].profile.name

            for message in val.messages:
                # Deduplication check: prevent duplicate event processing
                if message.id:
                    existing_event = await event_repo.get_by_message_id(message.id)
                    if existing_event:
                        logger.info(
                            f"Duplicate WhatsApp webhook event '{message.id}' received; skipping duplicate execution."
                        )
                        continue

                    await event_repo.record_event(
                        message_id=message.id,
                        from_phone_masked=mask_identifier(message.from_),
                        event_type=message.type,
                    )
                    await db_session.flush()

                await engine.handle_inbound_message(
                    from_phone=message.from_,
                    message=message,
                    display_name=profile_name,
                )

    return {"status": "ok"}
