"""Keyset streaming for warehouse backtests (no OFFSET; bounded page size)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from analytics.engine import DuckDBEngine
from analytics.historical_stream import iter_backtest_row_chunks


def test_iter_backtest_row_chunks_keyset_pagination() -> None:
    p = Path(tempfile.gettempdir()) / "tarka-backtest-stream-test.duckdb"
    p.unlink(missing_ok=True)
    eng = DuckDBEngine(p)
    try:
        eng._conn.execute(
            """
            INSERT INTO fraud_decisions (tenant_id, entity_id, created_at, trace_id, decision, score, payload_json)
            SELECT
              't1',
              'e',
              TIMESTAMP '2025-01-01 00:00:00' + (i * INTERVAL 1 SECOND),
              'tr' || CAST(i AS VARCHAR),
              CASE WHEN i % 3 = 0 THEN 'deny' WHEN i % 3 = 1 THEN 'review' ELSE 'allow' END,
              1.0,
              '{"amount": 10}'
            FROM generate_series(0, 1499) AS t(i)
            """
        )
        chunks = list(
            iter_backtest_row_chunks(
                eng,
                "fraud_decisions",
                "t1",
                "2024-12-31 00:00:00",
                "2025-06-01 00:00:00",
                chunk_size=1000,
            )
        )
        assert len(chunks) == 2
        assert len(chunks[0]) == 1000
        assert len(chunks[1]) == 500
        assert "payload_json" in chunks[0][0]
        assert "decision" in chunks[1][0]
    finally:
        eng.close()
        p.unlink(missing_ok=True)
