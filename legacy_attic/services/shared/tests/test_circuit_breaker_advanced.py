from __future__ import annotations

import asyncio
import contextlib

from circuit import AsyncCircuitBreaker, CircuitOpenError


def test_circuit_opens_after_threshold_and_recovers() -> None:
    async def run() -> None:
        cb = AsyncCircuitBreaker("upstream", failure_threshold=2, recovery_seconds=0.05)

        async def fail() -> None:
            raise RuntimeError("boom")

        with contextlib.suppress(RuntimeError):
            await cb.call(fail)
        with contextlib.suppress(RuntimeError):
            await cb.call(fail)
        try:
            await cb.call(fail)
            raise AssertionError("expected circuit to be open")
        except CircuitOpenError:
            pass

        await asyncio.sleep(0.06)
        result = await cb.call(lambda: asyncio.sleep(0, result="ok"))
        assert result == "ok"

    asyncio.run(run())


def test_concurrent_failures_trip_once_and_block_new_calls() -> None:
    async def run() -> None:
        cb = AsyncCircuitBreaker("concurrent", failure_threshold=1, recovery_seconds=0.1)

        async def fail() -> None:
            await asyncio.sleep(0.001)
            raise RuntimeError("err")

        tasks = [asyncio.create_task(cb.call(fail)) for _ in range(8)]
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await cb.call(lambda: asyncio.sleep(0, result=True))
            raise AssertionError("expected circuit to be open")
        except CircuitOpenError:
            pass

    asyncio.run(run())


def test_success_resets_failure_counter() -> None:
    async def run() -> None:
        cb = AsyncCircuitBreaker("reset", failure_threshold=3, recovery_seconds=0.1)

        async def fail() -> None:
            raise RuntimeError("x")

        with contextlib.suppress(RuntimeError):
            await cb.call(fail)
        ok = await cb.call(lambda: asyncio.sleep(0, result=1))
        assert ok == 1
        with contextlib.suppress(RuntimeError):
            await cb.call(fail)
        # Not open yet because success reset the failure streak.
        assert await cb.is_open() is False

    asyncio.run(run())
