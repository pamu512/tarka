"""Adaptive load shedding for evaluate: cap concurrent evaluations; shed graph + ML under pressure."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, AsyncIterator


class EvalLoadGuard:
    """When active evaluations >= max, new requests run with ``load_shed`` (skip graph + ML)."""

    def __init__(self, max_concurrent: int) -> None:
        self._max = max(1, int(max_concurrent))
        self._active = 0
        self._lock = asyncio.Lock()

    async def try_enter(self) -> tuple[bool, bool]:
        """Return ``(load_shed, acquired_slot)``.

        ``load_shed`` is True when this request should skip heavy dependency calls.
        ``acquired_slot`` is True when ``leave()`` must be called on exit.
        """
        async with self._lock:
            if self._active >= self._max:
                return (True, False)
            self._active += 1
            return (False, True)

    async def leave(self) -> None:
        async with self._lock:
            self._active = max(0, self._active - 1)


@asynccontextmanager
async def acquire_eval_capacity(app: Any) -> AsyncIterator[SimpleNamespace]:
    """Yield ``SimpleNamespace(load_shed=bool)``; releases slot when leaving context."""
    guard = getattr(app.state, "eval_load_guard", None)
    if guard is None:
        yield SimpleNamespace(load_shed=False)
        return
    load_shed, acquired = await guard.try_enter()
    try:
        yield SimpleNamespace(load_shed=load_shed)
    finally:
        if acquired:
            await guard.leave()
