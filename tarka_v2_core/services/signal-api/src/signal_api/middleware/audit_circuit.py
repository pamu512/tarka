"""
Postgres **audit** circuit breaker: bounded ``execute`` time; 5 consecutive timeouts → 60s degraded (no PG write).

NATS / Redis ingest fast-path are unchanged. See :func:`signal_api.durable_handover.durable_intent_handover`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)


class AuditPostgresCircuitBreaker:
    """
    Counts **asyncio.TimeoutError** only (from ``wait_for`` around audit persist). Other failures reset the streak.

    When open: :meth:`is_degraded` is true for ``degraded_duration_sec``; Postgres audit writes are skipped.
    """

    __slots__ = (
        "_consecutive_timeouts",
        "_degraded_until_monotonic",
        "_lock",
        "degraded_duration_sec",
        "execute_timeout_sec",
        "open_after_timeouts",
    )

    def __init__(
        self,
        *,
        execute_timeout_sec: float | None = None,
        open_after_timeouts: int | None = None,
        degraded_duration_sec: float | None = None,
    ) -> None:
        def _f(name: str, default: str) -> float:
            raw = (os.environ.get(name) or default).strip()
            try:
                return float(raw)
            except ValueError:
                return float(default)

        def _i(name: str, default: str) -> int:
            raw = (os.environ.get(name) or default).strip()
            try:
                return max(1, int(raw))
            except ValueError:
                return int(default)

        self.execute_timeout_sec = (
            float(execute_timeout_sec)
            if execute_timeout_sec is not None
            else _f("SIGNAL_AUDIT_EXECUTE_TIMEOUT_SEC", "5")
        )
        self.open_after_timeouts = (
            int(open_after_timeouts)
            if open_after_timeouts is not None
            else _i("SIGNAL_AUDIT_CIRCUIT_OPEN_AFTER_TIMEOUTS", "5")
        )
        self.degraded_duration_sec = (
            float(degraded_duration_sec)
            if degraded_duration_sec is not None
            else _f("SIGNAL_AUDIT_CIRCUIT_DEGRADED_SEC", "60")
        )
        self._consecutive_timeouts = 0
        self._degraded_until_monotonic = 0.0
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def is_degraded(self) -> bool:
        return time.monotonic() < self._degraded_until_monotonic

    def effective_execute_timeout_sec(self) -> float:
        """Return ``> 0`` to wrap audit persist with ``asyncio.wait_for``; ``<= 0`` disables the timeout."""
        return self.execute_timeout_sec

    async def record_success(self) -> None:
        async with self._get_lock():
            self._consecutive_timeouts = 0

    async def record_timeout(self) -> None:
        async with self._get_lock():
            self._consecutive_timeouts += 1
            if self._consecutive_timeouts >= self.open_after_timeouts:
                self._degraded_until_monotonic = time.monotonic() + self.degraded_duration_sec
                logger.warning(
                    "signal_audit_circuit_open degraded_sec=%s consecutive_timeouts=%s",
                    self.degraded_duration_sec,
                    self.open_after_timeouts,
                )
                self._consecutive_timeouts = 0

    async def record_non_timeout_failure(self) -> None:
        async with self._get_lock():
            self._consecutive_timeouts = 0


class AuditDegradedModeHeaderMiddleware:
    """ASGI middleware: append ``X-Signal-Audit-Degraded: 1`` when :class:`AuditPostgresCircuitBreaker` is degraded."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Any) -> None:
            if message["type"] == "http.response.start":
                app = scope.get("app")
                if app is not None:
                    cb = getattr(app.state, "audit_circuit", None)
                    if cb is not None and cb.is_degraded():
                        from starlette.datastructures import MutableHeaders

                        headers = MutableHeaders(raw=message["headers"])
                        headers.append("x-signal-audit-degraded", "1")
                        message["headers"] = headers.raw
            await send(message)

        await self.app(scope, receive, send_wrapper)
