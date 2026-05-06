"""Fingerprint (Fingerprint Pro) device intelligence adapter."""

from .client import FingerprintClient, FingerprintClientSettings, fingerprint_client_from_env
from .exceptions import (
    FingerprintAuthenticationError,
    FingerprintCircuitOpenError,
    FingerprintIdentificationFailedError,
    FingerprintIntegrationError,
    FingerprintMalformedPayloadError,
    FingerprintRateLimitError,
    FingerprintRequestNotFoundError,
    FingerprintUpstreamError,
    FingerprintWebhookSignatureError,
)
from .router import (
    build_fingerprint_webhook_router,
    fingerprint_webhook_router,
    verify_fingerprint_webhook_signature,
)
from .schemas import (
    EventsGetResponse,
    TarkaRiskSignal,
    TarkaVendorProvenance,
    fingerprint_events_response_to_tarka,
    parse_webhook_payload,
    webhook_payload_to_tarka,
)

__all__ = [
    "EventsGetResponse",
    "FingerprintAuthenticationError",
    "FingerprintCircuitOpenError",
    "FingerprintClient",
    "FingerprintClientSettings",
    "FingerprintIdentificationFailedError",
    "FingerprintIntegrationError",
    "FingerprintMalformedPayloadError",
    "FingerprintRateLimitError",
    "FingerprintRequestNotFoundError",
    "FingerprintUpstreamError",
    "FingerprintWebhookSignatureError",
    "TarkaRiskSignal",
    "TarkaVendorProvenance",
    "build_fingerprint_webhook_router",
    "fingerprint_client_from_env",
    "fingerprint_events_response_to_tarka",
    "fingerprint_webhook_router",
    "parse_webhook_payload",
    "verify_fingerprint_webhook_signature",
    "webhook_payload_to_tarka",
]
