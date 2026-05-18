"""Gate (Prompt 200): collect entity ids that matched a shadow rule in DuckDB."""

from __future__ import annotations

import json

import duckdb

import simulator


def test_collect_matched_entity_ids_from_flat_when() -> None:
    con = duckdb.connect(":memory:")
    con.execute(
        """
        CREATE TABLE raw_signals (
            session_id VARCHAR,
            signal_json VARCHAR,
            ingested_at TIMESTAMP
        )
        """,
    )
    rows = [
        ("s1", json.dumps({"ch": "hash_a", "user_id": "user-a"}), "2026-05-10 12:00:00"),
        ("s2", json.dumps({"ch": "hash_b", "user_id": "user-b"}), "2026-05-10 12:01:00"),
        ("s3", json.dumps({"ch": "hash_a", "user_id": "user-c"}), "2026-05-10 12:02:00"),
    ]
    for sid, sj, ts in rows:
        con.execute(
            "INSERT INTO raw_signals VALUES (?, ?, ?)",
            [sid, sj, ts],
        )

    rule = {
        "id": "shadow_gate_200",
        "when": [{"field": "canvas_hash", "op": "eq", "value": "hash_a"}],
    }
    ids = simulator.collect_matched_entity_ids(rule, duckdb_connection=con, lookback_days=None)
    assert sorted(ids) == ["user-a", "user-c"]
