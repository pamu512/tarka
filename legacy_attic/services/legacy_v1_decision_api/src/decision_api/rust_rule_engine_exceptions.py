"""Exceptions for Rust JSON rule engine (PyO3) and FFI circuit breaker."""

from __future__ import annotations

from typing import Any


class RustRuleEngineError(Exception):
    """Base class for Rust rule-plane failures when Python drift fallback is disabled."""


class RustRuleEngineCircuitOpenError(RustRuleEngineError):
    """Too many recent FFI failures — circuit is open; do not call Rust or Python parity engine."""

    def __init__(self, message: str, *, failures_in_window: int | None = None) -> None:
        super().__init__(message)
        self.failures_in_window = failures_in_window


class RustRuleEngineInvocationFailed(RustRuleEngineError):
    """Rust extension raised during evaluation (after structured diagnostics were logged)."""

    def __init__(
        self,
        message: str,
        *,
        cause: BaseException | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.cause = cause
        self.context = context or {}
