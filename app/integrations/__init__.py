"""
External Integrations Package.

Architectural Rule:
All third-party services, including future WhatsApp Cloud/Business API adapters,
payment gateways, and notification clients, must reside under this package.

Integrations must remain completely decoupled from core ordering and domain business logic.
Customer WhatsApp phone numbers and webhook payloads are processed internally within this layer
and must never be exposed directly to restaurant operational workflows or unmasked in log outputs.
"""
