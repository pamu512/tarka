"""Gate: Redis idempotency lock acquire/release for async handlers."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

_SRC_ORCH = Path(__file__).resolve().parents[1]
if str(_SRC_ORCH) not in sys.path:
    sys.path.insert(0, str(_SRC_ORCH))


def test_verify_and_lock_event_acquires_with_set_nx_ex() -> None:
    async def _run() -> None:
        from middleware.idempotency import verify_and_lock_event

        redis_client = AsyncMock()
        redis_client.set = AsyncMock(return_value=True)

        ok = await verify_and_lock_event(redis_client, "tarka:idemp:event-1", ttl_seconds=3600)
        assert ok is True
        redis_client.set.assert_awaited_once_with("tarka:idemp:event-1", "1", nx=True, ex=3600)

    asyncio.run(_run())


def test_verify_and_lock_event_returns_false_on_duplicate() -> None:
    async def _run() -> None:
        from middleware.idempotency import verify_and_lock_event

        redis_client = AsyncMock()
        redis_client.set = AsyncMock(return_value=None)

        ok = await verify_and_lock_event(redis_client, "tarka:idemp:event-1")
        assert ok is False

    asyncio.run(_run())


def test_release_lock_deletes_key() -> None:
    async def _run() -> None:
        from middleware.idempotency import release_lock

        redis_client = AsyncMock()
        redis_client.delete = AsyncMock(return_value=1)

        ok = await release_lock(redis_client, "tarka:idemp:event-1")
        assert ok is True
        redis_client.delete.assert_awaited_once_with("tarka:idemp:event-1")

    asyncio.run(_run())


def test_release_lock_noop_when_missing() -> None:
    async def _run() -> None:
        from middleware.idempotency import release_lock

        redis_client = AsyncMock()
        redis_client.delete = AsyncMock(return_value=0)

        ok = await release_lock(redis_client, "tarka:idemp:missing")
        assert ok is False

    asyncio.run(_run())


def test_verify_and_lock_rejects_empty_key() -> None:
    async def _run() -> None:
        from middleware.idempotency import IdempotencyKeyError, verify_and_lock_event

        with pytest.raises(IdempotencyKeyError, match="non-empty"):
            await verify_and_lock_event(AsyncMock(), "   ")

    asyncio.run(_run())


def test_verify_and_lock_requires_redis_client() -> None:
    async def _run() -> None:
        from middleware.idempotency import verify_and_lock_event

        with pytest.raises(RuntimeError, match="redis_client"):
            await verify_and_lock_event(None, "k")

    asyncio.run(_run())
