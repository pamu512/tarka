"""Incognia-specific errors mapped to stable Tarka integration codes."""

from __future__ import annotations

from typing import Any


class IncogniaIntegrationError(Exception):
    """Base for all Incognia adapter failures."""

    def __init__(self, message: str, *, code: str, http_status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class IncogniaAuthenticationError(IncogniaIntegrationError):
    """401/403 from token or business API (invalid client credentials or token)."""

    def __init__(self, message: str, *, http_status: int = 401) -> None:
        super().__init__(message, code="incognia_auth_failed", http_status=http_status)


class IncogniaClientError(IncogniaIntegrationError):
    """4xx responses other than auth/rate limit (validation, not found, etc.)."""

    def __init__(
        self, message: str, *, http_status: int, payload: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message, code="incognia_client_error", http_status=http_status)
        self.payload = payload


class IncogniaRateLimitError(IncogniaIntegrationError):
    """HTTP 429 or vendor ``Retry-After`` handling."""

    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message, code="incognia_rate_limited", http_status=429)
        self.retry_after_seconds = retry_after_seconds


class IncogniaUpstreamError(IncogniaIntegrationError):
    """5xx or unexpected HTTP status from Incognia API."""

    def __init__(self, message: str, *, http_status: int) -> None:
        super().__init__(message, code="incognia_upstream_error", http_status=http_status)


class IncogniaMalformedPayloadError(IncogniaIntegrationError):
    """JSON does not match expected models or token response is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="incognia_malformed_payload", http_status=None)


class IncogniaCircuitOpenError(IncogniaIntegrationError):
    """Client-side circuit breaker is open; short-circuiting outbound calls."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="incognia_circuit_open", http_status=None)
