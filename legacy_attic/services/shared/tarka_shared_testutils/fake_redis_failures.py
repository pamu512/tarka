from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any


class FakeRedisFailures:
    """Failure injection shim for Redis-like async clients in tests."""

    def __init__(self) -> None:
        self.fail_next_n: int = 0
        self.error_factory: Callable[[], Exception] = lambda: TimeoutError("simulated timeout")

    def inject(self, n: int, error_factory: Callable[[], Exception] | None = None) -> None:
        self.fail_next_n = max(0, int(n))
        if error_factory is not None:
            self.error_factory = error_factory

    async def maybe_fail(self) -> None:
        if self.fail_next_n <= 0:
            return
        self.fail_next_n -= 1
        raise self.error_factory()


class FakeRedisWithFailures:
    """Tiny Redis-like object that can fail on operations."""

    def __init__(self) -> None:
        self._failures = FakeRedisFailures()
        self._store: dict[str, Any] = {}

    @property
    def failures(self) -> FakeRedisFailures:
        return self._failures

    async def get(self, key: str) -> Any:
        await self._failures.maybe_fail()
        return self._store.get(key)

    async def set(self, key: str, value: Any) -> bool:
        await self._failures.maybe_fail()
        self._store[key] = value
        return True

    async def eval(self, _script: str, _numkeys: int, *_args: Any) -> int:
        await self._failures.maybe_fail()
        return 1

    async def ping(self) -> bool:
        await self._failures.maybe_fail()
        await asyncio.sleep(0)
        return True
