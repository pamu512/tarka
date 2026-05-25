"""Keyset pagination over DuckDB ``v_analytics_transactions``."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from orchestrator.analytics.duck_provider import DuckAnalyticsProvider
from orchestrator.analytics.transaction_cursor import (
    decode_transaction_cursor,
    encode_transaction_cursor,
)


def test_transaction_cursor_roundtrip() -> None:
    enc = encode_transaction_cursor(ts="2026-05-01T12:00:00", entity_id="ent-1", amount=42.5)
    dec = decode_transaction_cursor(enc)
    assert dec == ("2026-05-01T12:00:00", "ent-1", 42.5)


def test_list_analytics_transactions_keyset_pages() -> None:
    pytest.importorskip("duckdb")
    with tempfile.TemporaryDirectory() as tmp:
        pq = Path(tmp) / "seed.parquet"
        import duckdb

        con = duckdb.connect()
        con.execute(
            """
            CREATE TABLE seed AS
            SELECT * FROM (
              VALUES
                (TIMESTAMP '2026-05-10 10:00:00', 'US', 10.0, 'e-a'),
                (TIMESTAMP '2026-05-10 09:00:00', 'US', 20.0, 'e-b'),
                (TIMESTAMP '2026-05-10 08:00:00', 'GB', 30.0, 'e-c'),
                (TIMESTAMP '2026-05-10 07:00:00', 'GB', 40.0, 'e-d')
            ) AS t(ts, country, amount, entity_id)
            """,
        )
        con.execute(f"COPY seed TO '{pq}' (FORMAT PARQUET)")
        con.close()

        duck = DuckAnalyticsProvider(parquet_path=pq)
        duck.load()

        page1, c1, ms1 = duck.list_analytics_transactions(limit=2)
        assert len(page1) == 2
        assert ms1 >= 0
        assert c1 is not None

        page2, c2, _ms2 = duck.list_analytics_transactions(limit=2, cursor=c1)
        assert len(page2) == 2
        assert page2[0]["entity_id"] != page1[0]["entity_id"]

        page3, c3, _ = duck.list_analytics_transactions(limit=2, cursor=c2)
        # Four rows with limit=2: two pages exhaust the view; third page is empty.
        assert len(page3) == 0
        assert c3 is None

        ids = {r["entity_id"] for r in page1 + page2 + page3}
        assert ids == {"e-a", "e-b", "e-c", "e-d"}
