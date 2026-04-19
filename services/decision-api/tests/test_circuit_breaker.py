"""Async circuit breaker (shared) — open after consecutive failures."""

import asyncio

import pytest
from circuit import AsyncCircuitBreaker, CircuitOpenError


@pytest.mark.asyncio
async def test_circuit_opens_after_threshold():
    c = AsyncCircuitBreaker("t", failure_threshold=2, recovery_seconds=0.05)

    async def boom():
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        await c.call(boom)
    with pytest.raises(RuntimeError):
        await c.call(boom)
    with pytest.raises(CircuitOpenError):
        await c.call(boom)

    await asyncio.sleep(0.06)

    async def ok():
        return 1

    assert await c.call(ok) == 1
