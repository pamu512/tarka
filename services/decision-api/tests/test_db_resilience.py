from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.exc import OperationalError


async def _retry_db_op(op, *, attempts: int = 3, backoff_seconds: float = 0.01):
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            return await op()
        except OperationalError as exc:
            last_exc = exc
            if i == attempts - 1:
                raise
            await asyncio.sleep(backoff_seconds * (i + 1))
    if last_exc:
        raise last_exc
    return None


def test_retries_on_operational_error_then_succeeds():
    async def run() -> None:
        attempts = {"n": 0}

        async def op():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise OperationalError("select 1", {}, RuntimeError("deadlock detected"))
            return "ok"

        out = await _retry_db_op(op, attempts=4, backoff_seconds=0.001)
        assert out == "ok"
        assert attempts["n"] == 3

    asyncio.run(run())


def test_fails_after_retry_budget_exhausted():
    async def run() -> None:
        async def op():
            raise OperationalError("select 1", {}, RuntimeError("pool exhausted"))

        with pytest.raises(OperationalError):
            await _retry_db_op(op, attempts=2, backoff_seconds=0.001)

    asyncio.run(run())

