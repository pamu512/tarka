"""Fingerprint-specific errors mapped to stable Tarka integration codes."""

from __future__ import annotations


class FingerprintIntegrationError(Exception):
    """Base for all Fingerprint adapter failures."""

    def __init__(self, message: str, *, code: str, http_status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class FingerprintAuthenticationError(FingerprintIntegrationError):
    """403 responses: missing/invalid API key, wrong region, or token issues."""

    def __init__(self, message: str, *, fp_error_code: str, http_status: int = 403) -> None:
        super().__init__(message, code=f"fingerprint_auth:{fp_error_code}", http_status=http_status)
        self.fp_error_code = fp_error_code


class FingerprintRequestNotFoundError(FingerprintIntegrationError):
    """404 — request id is unknown to this application/region."""

    def __init__(self, message: str, *, request_id: str) -> None:
        super().__init__(message, code="fingerprint_request_not_found", http_status=404)
        self.request_id = request_id


class FingerprintRateLimitError(FingerprintIntegrationError):
    """HTTP 429 or vendor-reported rate limit (including embedded 429 in product errors)."""

    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message, code="fingerprint_rate_limited", http_status=429)
        self.retry_after_seconds = retry_after_seconds


class FingerprintUpstreamError(FingerprintIntegrationError):
    """5xx or unexpected HTTP status from Fingerprint API."""

    def __init__(self, message: str, *, http_status: int) -> None:
        super().__init__(message, code="fingerprint_upstream_error", http_status=http_status)


class FingerprintMalformedPayloadError(FingerprintIntegrationError):
    """JSON does not match expected envelope or required identification fields are missing."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="fingerprint_malformed_payload", http_status=None)


class FingerprintIdentificationFailedError(FingerprintIntegrationError):
    """HTTP 200 but identification product returned an error object."""

    def __init__(self, message: str, *, fp_error_code: str | None = None) -> None:
        code = "fingerprint_identification_failed"
        if fp_error_code:
            code = f"{code}:{fp_error_code}"
        super().__init__(message, code=code, http_status=200)
        self.fp_error_code = fp_error_code


class FingerprintWebhookSignatureError(FingerprintIntegrationError):
    """HMAC verification failed or signature header missing when enforcement is enabled."""

    def __init__(self, message: str, *, missing_header: bool = False) -> None:
        code = (
            "fingerprint_webhook_signature_missing"
            if missing_header
            else "fingerprint_webhook_signature_invalid"
        )
        super().__init__(message, code=code, http_status=403 if not missing_header else 400)
        self.missing_header = missing_header


class FingerprintCircuitOpenError(FingerprintIntegrationError):
    """Client-side circuit breaker is open; short-circuiting outbound calls."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="fingerprint_circuit_open", http_status=None)
