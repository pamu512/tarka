"""Tests for Redis → DuckDB Anumana sink (batch RPOP + append ``ingested_raw``)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
for _p in (_SRC_ORCH, _SRC_INGESTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from orchestrator.analytics.duck_provider import DuckAnalyticsProvider  # noqa: E402
from orchestrator.workers.anumana_nats_duck_sink import (  # noqa: E402
    flush_redis_to_analytics,
    rpop_many,
)


class _FakeRedis:
    """Minimal async Redis: ``LPUSH`` prepends; ``RPOP`` pops tail (matches Redis list semantics)."""

    def __init__(self) -> None:
        self._lists: dict[str, list[bytes]] = {}

    async def lpush(self, key: str, value: bytes) -> int:
        lst = self._lists.setdefault(key, [])
        lst.insert(0, value)
        return 1

    async def rpop(self, key: str) -> bytes | None:
        lst = self._lists.get(key)
        if not lst:
            return None
        return lst.pop()


def _telemetry_envelope(**extra: object) -> dict[str, object]:
    base: dict[str, object] = {
        "schema": "tarka.browser_telemetry.v1",
        "ts": "2026-05-01T12:00:00+00:00",
        "ingress_ip": "198.51.100.1",
        "client_claimed_ip": "192.0.2.1",
        "canvas_fingerprint": "ab" * 32,
        "canvas_raster_digest_hex": "deadbeef",
        "tenant_id": "t1",
        "device_session_id": "sess-1",
        "telemetry_packet": {"k": "v"},
    }
    base.update(extra)
    return base


def test_rpop_many_fifo_after_lpush() -> None:
    async def _run() -> None:
        r = _FakeRedis()
        key = "anumana:browser_telemetry"
        await r.lpush(key, b"a")
        await r.lpush(key, b"b")
        got = await rpop_many(r, key, 10)
        assert got == [b"a", b"b"]

    asyncio.run(_run())


def test_flush_redis_to_duck_writes_ingested_raw(tmp_path: Path) -> None:
    pq = tmp_path / "seed.parquet"
    import duckdb as duckdb_mod

    con = duckdb_mod.connect()
    con.execute(
        f"""
        COPY (
          SELECT
            TIMESTAMP '2026-01-01 00:00:00' AS ts,
            'US' AS country,
            10.0::DOUBLE AS amount,
            '00000000-0000-0000-0000-000000000001' AS entity_id
        ) TO '{pq.as_posix()}' (FORMAT PARQUET);
        """,
    )
    con.close()

    async def _run() -> None:
        r = _FakeRedis()
        key = "anumana:browser_telemetry"
        env = _telemetry_envelope()
        await r.lpush(key, json.dumps(env, separators=(",", ":")).encode("utf-8"))

        duck = DuckAnalyticsProvider(parquet_path=pq)
        duck.load()
        stats = await flush_redis_to_analytics(r, duck, redis_key=key, max_items=50)
        assert stats == {"popped": 1, "written": 1, "dropped": 0}

        rows, _next, _ms = duck.list_analytics_transactions(limit=50)
        assert len(rows) >= 2
        assert any("sdk_source" in str(row.get("metadata") or "") for row in rows)

    asyncio.run(_run())


def test_flush_drops_malformed_json() -> None:
    async def _run() -> None:
        r = _FakeRedis()
        key = "k"
        await r.lpush(key, b"not-json{{{")
        duck = DuckAnalyticsProvider()
        duck.load()
        stats = await flush_redis_to_analytics(r, duck, redis_key=key, max_items=10)
        assert stats["popped"] == 1
        assert stats["written"] == 0
        assert stats["dropped"] == 1

    asyncio.run(_run())
