import logging
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import httpx

from app.core.config import get_settings
from app.integrations.whatsapp.schemas import OutboundMessageRecord
from app.services.session import mask_identifier

logger = logging.getLogger("whatsapp_ordering.integrations.whatsapp")
settings = get_settings()


def sanitize_sensitive_string(
    text: str,
    secret_values: Optional[List[Optional[str]]] = None,
) -> str:
    """
    Remove secrets and mask phone numbers in diagnostic messages.
    Guarantees secrets and customer PII are never leaked in logs or persisted errors.
    """
    if not text:
        return ""

    # Mask custom secrets if provided
    if secret_values:
        for secret in secret_values:
            if secret and len(secret) > 3:
                text = text.replace(secret, "[MASKED_SECRET]")

    # Mask any Bearer tokens
    text = re.sub(r"Bearer\s+[A-Za-z0-9_\-\.]+", "Bearer [MASKED_TOKEN]", text)

    # Mask telephone numbers (8 to 15 digits, optionally with leading +)
    text = re.sub(r"\+?\b\d{8,15}\b", "[MASKED_PHONE]", text)

    return text


# ---------------------------------------------------------------------------
# Base WhatsApp Client Interface
# ---------------------------------------------------------------------------

class BaseWhatsAppClient(ABC):
    """
    Abstract interface for WhatsApp messaging providers.
    All implementations maintain an in-memory sent_messages buffer for test inspection.
    """
    def __init__(self) -> None:
        self.sent_messages: List[OutboundMessageRecord] = []

    def clear_sent_messages(self) -> None:
        """
        Clear in-memory recorded messages (useful between test cases).
        """
        self.sent_messages.clear()

    @abstractmethod
    async def send_text(self, to: str, text: str) -> OutboundMessageRecord:
        """
        Send a plain text message.
        """
        pass

    @abstractmethod
    async def send_buttons(
        self, to: str, text: str, buttons: List[Dict[str, str]]
    ) -> OutboundMessageRecord:
        """
        Send interactive button reply message (up to 3 buttons).
        Each button: {"id": "CALLBACK_ID", "title": "Button Title"}
        """
        pass

    @abstractmethod
    async def send_list(
        self,
        to: str,
        text: str,
        button_label: str,
        sections: List[Dict[str, Any]],
    ) -> OutboundMessageRecord:
        """
        Send interactive list message.
        sections format:
        [
            {
                "title": "Section Title",
                "rows": [
                    {"id": "ROW_ID", "title": "Row Title", "description": "Optional desc"}
                ]
            }
        ]
        """
        pass


# ---------------------------------------------------------------------------
# Mock WhatsApp Client (Development & Testing)
# ---------------------------------------------------------------------------

class MockWhatsAppClient(BaseWhatsAppClient):
    """
    Mock WhatsApp client for local testing and simulation without external Meta API calls.
    Records outbound messages into memory for verification.
    """
    def __init__(self) -> None:
        super().__init__()

    async def send_text(self, to: str, text: str) -> OutboundMessageRecord:
        record = OutboundMessageRecord(
            to=to,
            type="text",
            body=text,
            success=True,
            payload={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"preview_url": False, "body": text},
            },
        )
        self.sent_messages.append(record)
        masked_to = mask_identifier(to)
        logger.info(f"[MOCK] Dispatched WhatsApp text message to {masked_to}")
        return record

    async def send_buttons(
        self, to: str, text: str, buttons: List[Dict[str, str]]
    ) -> OutboundMessageRecord:
        formatted_buttons = [
            {
                "type": "reply",
                "reply": {"id": btn["id"], "title": btn["title"][:20]},
            }
            for btn in buttons[:3]
        ]
        record = OutboundMessageRecord(
            to=to,
            type="button",
            body=text,
            buttons=buttons,
            success=True,
            payload={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": text},
                    "action": {"buttons": formatted_buttons},
                },
            },
        )
        self.sent_messages.append(record)
        masked_to = mask_identifier(to)
        logger.info(f"[MOCK] Dispatched WhatsApp button message to {masked_to}")
        return record

    async def send_list(
        self,
        to: str,
        text: str,
        button_label: str,
        sections: List[Dict[str, Any]],
    ) -> OutboundMessageRecord:
        record = OutboundMessageRecord(
            to=to,
            type="list",
            body=text,
            sections=sections,
            success=True,
            payload={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "interactive",
                "interactive": {
                    "type": "list",
                    "body": {"text": text},
                    "action": {
                        "button": button_label[:20],
                        "sections": sections,
                    },
                },
            },
        )
        self.sent_messages.append(record)
        masked_to = mask_identifier(to)
        logger.info(f"[MOCK] Dispatched WhatsApp list message to {masked_to}")
        return record


# ---------------------------------------------------------------------------
# Real Meta WhatsApp Cloud API Client
# ---------------------------------------------------------------------------

class MetaWhatsAppClient(BaseWhatsAppClient):
    """
    Real Meta WhatsApp Cloud API Client.
    Communicates asynchronously via HTTP with Meta Graph API endpoints.
    Formats normalized payloads, handles HTTP errors and timeouts safely,
    and protects secrets and customer phone numbers.
    """
    def __init__(
        self,
        access_token: Optional[str] = None,
        phone_number_id: Optional[str] = None,
        api_url: Optional[str] = None,
        timeout: Optional[float] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        super().__init__()
        self.access_token = access_token or settings.effective_whatsapp_token
        self.phone_number_id = phone_number_id or settings.WHATSAPP_PHONE_NUMBER_ID
        self.api_url = (api_url or settings.effective_whatsapp_api_url).rstrip("/")
        self.timeout = timeout or settings.WHATSAPP_REQUEST_TIMEOUT
        self._custom_http_client = http_client

    def _sanitize(self, raw_str: str) -> str:
        """
        Sanitize strings before logging or storing.
        """
        secrets_to_mask = [
            self.access_token,
            settings.WHATSAPP_APP_SECRET,
            settings.SECRET_KEY,
        ]
        return sanitize_sensitive_string(raw_str, secret_values=secrets_to_mask)

    async def _post_to_meta(
        self, record: OutboundMessageRecord, payload: Dict[str, Any]
    ) -> OutboundMessageRecord:
        """
        Execute authenticated async HTTP POST to Meta WhatsApp Cloud API messages endpoint.
        Format: POST https://graph.facebook.com/{version}/{phone_number_id}/messages
        Headers:
            Authorization: Bearer <access_token>
            Content-Type: application/json
        """
        record.payload = payload
        masked_to = mask_identifier(record.to)

        # 1. Verify credentials present
        if not self.access_token or not self.phone_number_id:
            record.success = False
            record.error = "Meta WhatsApp credentials unconfigured (missing access token or phone number id)."
            self.sent_messages.append(record)
            logger.error(
                f"Failed to dispatch WhatsApp message to {masked_to}: {record.error}"
            )
            return record

        endpoint_url = f"{self.api_url}/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        # 2. Perform async HTTP request
        try:
            if self._custom_http_client:
                resp = await self._custom_http_client.post(
                    endpoint_url, json=payload, headers=headers, timeout=self.timeout
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        endpoint_url, json=payload, headers=headers
                    )

            # 3. Handle response
            if resp.status_code in (200, 201):
                record.success = True
                try:
                    resp_json = resp.json()
                    messages = resp_json.get("messages", [])
                    if messages and isinstance(messages, list) and "id" in messages[0]:
                        record.meta_message_id = messages[0]["id"]
                except Exception as parse_err:
                    logger.warning(
                        f"Could not parse Meta response JSON ({parse_err}), but received HTTP {resp.status_code}"
                    )
                logger.info(
                    f"Successfully dispatched Meta WhatsApp {record.type} message to {masked_to} (meta_id={record.meta_message_id})"
                )
            else:
                record.success = False
                try:
                    err_json = resp.json()
                    err_obj = err_json.get("error", {})
                    err_code = err_obj.get("code", "unknown")
                    err_message = self._sanitize(err_obj.get("message", resp.text))
                    record.error = f"Meta API error (code {err_code}, HTTP {resp.status_code}): {err_message}"
                except Exception:
                    record.error = f"Meta API HTTP {resp.status_code}: {self._sanitize(resp.text[:200])}"

                logger.error(
                    f"Meta WhatsApp Cloud API error dispatching to {masked_to}: {record.error}"
                )

        except httpx.TimeoutException:
            record.success = False
            record.error = f"Meta WhatsApp API request timed out after {self.timeout} seconds."
            logger.error(
                f"Timeout dispatching WhatsApp message to {masked_to} after {self.timeout}s"
            )
        except httpx.RequestError as req_err:
            record.success = False
            record.error = self._sanitize(f"Network error contacting Meta WhatsApp API: {type(req_err).__name__}")
            logger.error(
                f"Network error dispatching WhatsApp message to {masked_to}: {record.error}"
            )
        except Exception as unexp_err:
            record.success = False
            record.error = self._sanitize(f"Unexpected error in Meta WhatsApp client: {type(unexp_err).__name__}")
            logger.error(
                f"Unexpected error dispatching WhatsApp message to {masked_to}: {record.error}",
                exc_info=True,
            )

        self.sent_messages.append(record)
        return record

    async def send_text(self, to: str, text: str) -> OutboundMessageRecord:
        """
        Send a plain text message via Meta Cloud API.
        """
        record = OutboundMessageRecord(to=to, type="text", body=text)
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
        return await self._post_to_meta(record, payload)

    async def send_buttons(
        self, to: str, text: str, buttons: List[Dict[str, str]]
    ) -> OutboundMessageRecord:
        """
        Send interactive button reply message via Meta Cloud API.
        Meta constraints: up to 3 buttons, button title max 20 chars.
        """
        record = OutboundMessageRecord(
            to=to, type="button", body=text, buttons=buttons
        )
        formatted_buttons = [
            {
                "type": "reply",
                "reply": {"id": btn["id"], "title": btn["title"][:20]},
            }
            for btn in buttons[:3]
        ]
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": text},
                "action": {"buttons": formatted_buttons},
            },
        }
        return await self._post_to_meta(record, payload)

    async def send_list(
        self,
        to: str,
        text: str,
        button_label: str,
        sections: List[Dict[str, Any]],
    ) -> OutboundMessageRecord:
        """
        Send interactive list message via Meta Cloud API.
        Meta constraints: button label max 20 chars, max 10 sections.
        """
        record = OutboundMessageRecord(
            to=to, type="list", body=text, sections=sections
        )
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": text},
                "action": {
                    "button": button_label[:20],
                    "sections": sections,
                },
            },
        }
        return await self._post_to_meta(record, payload)


# ---------------------------------------------------------------------------
# Unified Facade / Factory
# ---------------------------------------------------------------------------

class WhatsAppClient(BaseWhatsAppClient):
    """
    Unified WhatsApp Client Facade.
    Switches between MockWhatsAppClient and MetaWhatsAppClient based on configuration
    (WHATSAPP_MODE='mock' | 'meta' or WHATSAPP_USE_MOCK=True/False).
    Maintains 100% backward compatibility with all existing imports, methods, and attributes.
    """
    def __init__(
        self,
        mode: Optional[str] = None,
        api_token: Optional[str] = None,
        phone_number_id: Optional[str] = None,
        api_url: Optional[str] = None,
    ) -> None:
        target_mode = (mode or settings.WHATSAPP_MODE).lower()
        if not settings.WHATSAPP_USE_MOCK:
            target_mode = "meta"

        if target_mode == "meta":
            self._delegate: BaseWhatsAppClient = MetaWhatsAppClient(
                access_token=api_token,
                phone_number_id=phone_number_id,
                api_url=api_url,
            )
        else:
            self._delegate = MockWhatsAppClient()

        # After initializing _delegate, super().__init__() will set self.sent_messages = []
        super().__init__()

    @property
    def sent_messages(self) -> List[OutboundMessageRecord]:
        return self._delegate.sent_messages

    @sent_messages.setter
    def sent_messages(self, value: List[OutboundMessageRecord]) -> None:
        self._delegate.sent_messages = value

    def clear_sent_messages(self) -> None:
        self._delegate.clear_sent_messages()

    async def send_text(self, to: str, text: str) -> OutboundMessageRecord:
        return await self._delegate.send_text(to=to, text=text)

    async def send_buttons(
        self, to: str, text: str, buttons: List[Dict[str, str]]
    ) -> OutboundMessageRecord:
        return await self._delegate.send_buttons(to=to, text=text, buttons=buttons)

    async def send_list(
        self,
        to: str,
        text: str,
        button_label: str,
        sections: List[Dict[str, Any]],
    ) -> OutboundMessageRecord:
        return await self._delegate.send_list(
            to=to, text=text, button_label=button_label, sections=sections
        )


def get_whatsapp_client(mode: Optional[str] = None) -> BaseWhatsAppClient:
    """
    Factory creating configured WhatsApp client instance.
    """
    return WhatsAppClient(mode=mode)


# Global singleton instance
whatsapp_client = get_whatsapp_client()
