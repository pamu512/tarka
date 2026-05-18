from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

"""Lightweight async circuit breaker for outbound HTTP / Redis / Postgres-adjacent calls (R2).

Matches common **resilience4j**-style semantics for the COUNTING strategy: after
``failure_threshold`` **consecutive** failures, the breaker opens and rejects new calls until
``recovery_seconds`` elapse (wait in open state), then one probe is allowed; success **closes**
and resets the counter, failure **re-opens** the circuit.
"""
T = TypeVar("T")


class CircuitOpenError(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"circuit open: {name}")


class AsyncCircuitBreaker:
    __slots__ = ("_name", "_threshold", "_recovery", "_failures", "_blocked_until", "_lock")

    def __init__(
        self, name: str, *, failure_threshold: int = 5, recovery_seconds: float = 30.0
    ) -> None:
        self._name = name
        self._threshold = max(1, failure_threshold)
        self._recovery = max(0.01, float(recovery_seconds))
        self._failures = 0
        self._blocked_until: float | None = None
        self._lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return self._name

    def _now(self) -> float:
        return time.monotonic()

    async def is_open(self) -> bool:
        async with self._lock:
            return self._is_blocked_locked()

    def _is_blocked_locked(self) -> bool:
        if self._blocked_until is None:
            return False
        if self._now() >= self._blocked_until:
            self._blocked_until = None
            return False
        return True

    async def call(self, factory: Callable[[], Awaitable[T]]) -> T:
        async with self._lock:
            if self._is_blocked_locked():
                raise CircuitOpenError(self._name)

        try:
            result = await factory()
        except BaseException:
            async with self._lock:
                self._failures += 1
                if self._failures >= self._threshold:
                    self._blocked_until = self._now() + self._recovery
            raise

        async with self._lock:
            self._failures = 0
            self._blocked_until = None
        return result
