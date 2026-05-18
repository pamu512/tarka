"""Unit tests for Postgres → ClickHouse inference log sync helpers."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from analytics.syncer import (
    SyncWorker,
    SyncWorkerConfig,
    SyncWorkerStats,
    _next_retry_delay_seconds,
    gather_with_concurrency,
)


def test_next_retry_delay_exponential_cap() -> None:
    assert _next_retry_delay_seconds(
        failure_count_before_increment=0, backoff_base_sec=2.0, backoff_max_sec=100.0
    ) == pytest.approx(2.0)
    assert _next_retry_delay_seconds(
        failure_count_before_increment=3, backoff_base_sec=2.0, backoff_max_sec=100.0
    ) == pytest.approx(16.0)
    assert _next_retry_delay_seconds(
        failure_count_before_increment=30, backoff_base_sec=2.0, backoff_max_sec=100.0
    ) == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_gather_with_concurrency_limits_parallelism() -> None:
    running = 0
    peak = 0
    lock = asyncio.Lock()

    async def task(_: int) -> None:
        nonlocal running, peak
        async with lock:
            running += 1
            peak = max(peak, running)
        await asyncio.sleep(0.05)
        async with lock:
            running -= 1

    await gather_with_concurrency([task(i) for i in range(8)], limit=3)
    assert peak <= 3


@pytest.mark.asyncio
async def test_process_chunk_marks_failed_on_uniq_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="UPDATE 1")

    @asynccontextmanager
    async def _acquire() -> Any:
        yield conn

    pool = MagicMock()
    pool.acquire = _acquire

    ch = MagicMock()
    cfg = SyncWorkerConfig(batch_size=10, max_concurrent_batches=2, clickhouse_table="t")
    worker = SyncWorker(
        pool, ch, clickhouse_database="default", config=cfg, run_clickhouse_sync=lambda fn: fn()
    )

    row = {
        "id": uuid4(),
        "trace_id": uuid4(),
        "tenant_id": "t1",
        "entity_id": "e1",
        "event_type": "eval",
        "decision": "allow",
        "score": 1.0,
        "tags": [],
        "rule_hits": [],
        "payload_snapshot": None,
        "created_at": datetime.now(UTC),
        "sync_status": "PENDING",
        "sync_failure_count": 0,
    }

    stats = SyncWorkerStats()
    monkeypatch.setattr(worker, "_ch_insert_versioned", AsyncMock())
    monkeypatch.setattr(worker, "_ch_uniq_count_for_ids", AsyncMock(return_value=0))

    await worker._process_chunk([row], stats)  # type: ignore[arg-type]

    assert stats.chunks_failed == 1
    assert stats.rows_marked_failed == 1
    conn.execute.assert_called()
