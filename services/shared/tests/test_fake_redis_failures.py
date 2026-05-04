from __future__ import annotations

import asyncio

import pytest

from tarka_shared_testutils.fake_redis_failures import FakeRedisWithFailures


def test_timeout_failure_injection() -> None:
    async def run() -> None:
        redis = FakeRedisWithFailures()
        redis.failures.inject(1, lambda: TimeoutError("sim timeout"))
        with pytest.raises(TimeoutError):
            await redis.ping()

    asyncio.run(run())


def test_connection_pool_exhaustion_style_error() -> None:
    async def run() -> None:
        redis = FakeRedisWithFailures()
        redis.failures.inject(1, lambda: ConnectionError("pool exhausted"))
        with pytest.raises(ConnectionError):
            await redis.get("k")

    asyncio.run(run())


def test_lua_eval_failure_injection() -> None:
    async def run() -> None:
        redis = FakeRedisWithFailures()
        redis.failures.inject(1, lambda: RuntimeError("lua eval failed"))
        with pytest.raises(RuntimeError):
            await redis.eval("return 1", 0)

    asyncio.run(run())

