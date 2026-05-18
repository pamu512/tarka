"""Gate (Prompt 193): DuckDB what-if simulator confusion matrix vs Postgres labels."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import pytest

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import simulator  # noqa: E402


def _seed_duck(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE raw_signals (
            ingested_at TIMESTAMP,
            session_id VARCHAR,
            signal_json VARCHAR,
            nats_stream_seq BIGINT
        )
        """,
    )
    rows = [
        (
            "2026-05-18 10:00:00",
            "sess-clean-1",
            json.dumps({"px": False, "dm": 8, "sid": "sess-clean-1"}),
            1,
        ),
        (
            "2026-05-18 10:01:00",
            "sess-clean-2",
            json.dumps({"px": False, "dm": 4, "sid": "sess-clean-2"}),
            2,
        ),
        (
            "2026-05-18 10:02:00",
            "sess-fraud-1",
            json.dumps({"px": True, "dm": 16, "sid": "sess-fraud-1"}),
            3,
        ),
        (
            "2026-05-18 10:03:00",
            "sess-fraud-miss",
            json.dumps({"px": False, "dm": 2, "sid": "sess-fraud-miss"}),
            4,
        ),
    ]
    con.executemany(
        "INSERT INTO raw_signals VALUES (?, ?, ?, ?)",
        rows,
    )


def test_confusion_matrix_proxy_rule() -> None:
    con = duckdb.connect(":memory:")
    _seed_duck(con)
    rule = {
        "id": "shadow_proxy_probe",
        "when": [{"op": "is_true", "field": "is_proxy"}],
    }
    labels = simulator.LabelSets(
        fraud_keys=frozenset({"sess-fraud-1", "sess-fraud-miss"}),
        cased_keys=frozenset({"sess-fraud-1", "sess-fraud-miss"}),
    )
    report = simulator.run_what_if_simulation(
        rule,
        labels=labels,
        duckdb_connection=con,
    )
    cm = report.confusion_matrix
    assert cm.tp == 1
    assert cm.fp == 0
    assert cm.fn == 1
    assert cm.tn == 2
    assert report.matched_users == 1
    assert report.evaluated_via == "duckdb_sql"
    assert "is_proxy" in (report.sql_predicate or "") or "px" in (report.sql_predicate or "")


def test_fp_matches_user_with_no_case() -> None:
    con = duckdb.connect(":memory:")
    con.execute(
        """
        CREATE TABLE raw_signals (
            ingested_at TIMESTAMP,
            session_id VARCHAR,
            signal_json VARCHAR,
            nats_stream_seq BIGINT
        )
        """,
    )
    con.execute(
        "INSERT INTO raw_signals VALUES (CURRENT_TIMESTAMP, ?, ?, 1)",
        [
            "sess-no-case",
            json.dumps({"px": True, "dm": 8, "sid": "sess-no-case"}),
        ],
    )
    rule = {"id": "r1", "when": [{"op": "is_true", "field": "px"}]}
    labels = simulator.LabelSets(fraud_keys=frozenset(), cased_keys=frozenset())
    report = simulator.run_what_if_simulation(rule, labels=labels, duckdb_connection=con)
    assert report.confusion_matrix.fp == 1
    assert report.confusion_matrix.tp == 0


def test_condition_to_sql_numeric() -> None:
    sql = simulator.condition_to_sql({"op": "gte", "field": "dm", "value": 8})
    assert "DOUBLE" in sql
    assert ">=" in sql


def test_normalize_ruleset_envelope() -> None:
    doc = {"rules": [{"id": "a", "when": [{"op": "is_true", "field": "px"}]}]}
    rule = simulator.normalize_rule(doc)
    assert rule["id"] == "a"
