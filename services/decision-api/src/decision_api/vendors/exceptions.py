"""Structured vendor integration failures (no silent degradation)."""

from __future__ import annotations

import uuid
from typing import Any


class VendorTimeoutError(Exception):
    """Raised when a vendor call exceeds the caller budget or per-attempt HTTP timeouts after retries."""

    def __init__(
        self,
        *,
        vendor_id: str,
        budget_ms: float,
        trace_id: uuid.UUID | None,
        message: str = "vendor request exceeded latency budget",
    ) -> None:
        super().__init__(message)
        self.vendor_id = vendor_id
        self.budget_ms = budget_ms
        self.trace_id = trace_id
        self.reason_code = "VENDOR_TIMEOUT"

    def to_detail(self) -> dict[str, Any]:
        return {
            "reason_code": self.reason_code,
            "vendor_id": self.vendor_id,
            "budget_ms": self.budget_ms,
            "trace_id": str(self.trace_id) if self.trace_id else None,
            "message": str(self),
        }


class VendorUpstreamError(Exception):
    """Raised when the vendor returns a non-success payload or HTTP error that must not be masked."""

    def __init__(
        self,
        *,
        vendor_id: str,
        message: str,
        trace_id: uuid.UUID | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.vendor_id = vendor_id
        self.trace_id = trace_id
        self.http_status = http_status
        self.reason_code = "VENDOR_UPSTREAM_ERROR"

    def to_detail(self) -> dict[str, Any]:
        return {
            "reason_code": self.reason_code,
            "vendor_id": self.vendor_id,
            "trace_id": str(self.trace_id) if self.trace_id else None,
            "http_status": self.http_status,
            "message": str(self),
        }


class VendorAuditConfigurationError(RuntimeError):
    """Raised when Postgres audit context is missing for a plugin invocation."""

    reason_code = "VENDOR_AUDIT_CONTEXT_MISSING"
