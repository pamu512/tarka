"""DuckDB analytics provider and ``GET /v1/analytics/velocity`` gate checks."""

from __future__ import annotations

import asyncio
import statistics
import sys
from pathlib import Path

import duckdb
import pytest
from starlette.testclient import TestClient

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
for _p in (_SRC_ORCH, _SRC_INGESTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from orchestrator.analytics.duck_provider import DuckAnalyticsProvider  # noqa: E402
from orchestrator.main import create_app  # noqa: E402


def _write_n_row_parquet(path: Path, n: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
          SELECT
            (TIMESTAMP '2026-01-01 00:00:00' + (i * INTERVAL 1 SECOND)) AS ts,
            (['US', 'CA', 'GB', 'DE', 'FR'])[1 + (i % 5)] AS country,
            (10 + (i % 97))::DOUBLE AS amount,
            uuid() AS entity_id
          FROM range({n}) t(i)
        ) TO '{path.as_posix()}' (FORMAT PARQUET);
        """,
    )
    con.close()
    return path


def test_velocity_endpoint_uses_seed_parquet() -> None:
    app = create_app(rule_engine_url="http://rules.test", shadow_agent_url=None)
    with TestClient(app) as client:
        r = client.get("/v1/analytics/velocity")
    assert r.status_code == 200
    body = r.json()
    assert "rows" in body and "query_ms" in body
    assert isinstance(body["rows"], list)
    assert len(body["rows"]) >= 1
    row0 = body["rows"][0]
    assert set(row0.keys()) == {"minute_bucket", "country", "txn_count"}
    assert body["query_ms"] >= 0


@pytest.mark.parametrize("n", [100_000])
def test_velocity_query_under_5ms_while_slow_async_guard(n: int, tmp_path: Path) -> None:
    """
    Gate: DuckDB aggregation stays fast on ~100k rows while the event loop is busy
    (simulated Shadow / long-running coroutine). Work runs in a thread via ``asyncio.to_thread``.
    """
    pq = _write_n_row_parquet(tmp_path / "big.parquet", n)
    provider = DuckAnalyticsProvider(parquet_path=pq)
    provider.load()

    async def _exercise() -> None:
        slow_guard = asyncio.create_task(asyncio.sleep(2.0))
        try:
            for _ in range(5):
                await asyncio.to_thread(provider.velocity_sql_execute_ms)
            samples: list[float] = []
            for _ in range(20):
                samples.append(await asyncio.to_thread(provider.velocity_sql_execute_ms))
                await asyncio.sleep(0)
            med = statistics.median(samples)
            assert med < 5.0, (
                f"median DuckDB execute+fetchall was {med} ms (target < 5 ms for {n} rows); "
                f"all samples ms={samples!r}"
            )
            assert max(samples) < 15.0, (
                f"tail latency {max(samples)} ms too high while slow task still running"
            )
            assert not slow_guard.done()
        finally:
            slow_guard.cancel()
            try:
                await slow_guard
            except asyncio.CancelledError:
                pass

    asyncio.run(_exercise())
    provider.close()
