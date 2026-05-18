"""Gate (Prompt 196): analyst hypothesis blocked unless 7-day DuckDB FPR < 0.1%."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import simulator  # noqa: E402


def _seed_many_clean_and_few_proxy(
    con: duckdb.DuckDBPyConnection,
    *,
    clean_count: int,
    proxy_count: int,
    canvas: str,
) -> None:
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
    base = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
    rows: list[tuple] = []
    seq = 0
    for i in range(clean_count):
        seq += 1
        rows.append(
            (
                base + timedelta(minutes=i),
                f"clean-{i}",
                json.dumps({"px": False, "ch": f"unique_{i}", "sid": f"clean-{i}"}),
                seq,
            ),
        )
    for j in range(proxy_count):
        seq += 1
        rows.append(
            (
                base + timedelta(minutes=clean_count + j),
                f"proxy-{j}",
                json.dumps({"px": True, "ch": canvas, "sid": f"proxy-{j}"}),
                seq,
            ),
        )
    con.executemany("INSERT INTO raw_signals VALUES (?, ?, ?, ?)", rows)


def test_fpr_gate_passes_when_below_point_one_percent() -> None:
    con = duckdb.connect(":memory:")
    canvas = "shared_canvas_gate_pass"
    _seed_many_clean_and_few_proxy(con, clean_count=2000, proxy_count=1, canvas=canvas)
    rule = {
        "id": "scout_canvas_burst_shared",
        "when": [{"op": "eq", "field": "canvas_hash", "value": canvas}],
    }
    labels = simulator.LabelSets(fraud_keys=frozenset(), cased_keys=frozenset())
    validation = simulator.validate_hypothesis_backtest(
        rule,
        labels=labels,
        duckdb_connection=con,
        lookback_days=7,
        max_false_positive_rate=0.001,
    )
    assert validation.passed is True
    assert validation.false_positive_rate < 0.001
    assert validation.as_dict()["analyst_suggestion_allowed"] is True


def test_fpr_gate_blocks_at_point_one_percent() -> None:
    con = duckdb.connect(":memory:")
    canvas = "shared_canvas_gate_block"
    _seed_many_clean_and_few_proxy(con, clean_count=999, proxy_count=1, canvas=canvas)
    rule = {
        "id": "scout_canvas_burst_block",
        "when": [{"op": "is_true", "field": "is_proxy"}],
    }
    labels = simulator.LabelSets(fraud_keys=frozenset(), cased_keys=frozenset())
    validation = simulator.validate_hypothesis_backtest(
        rule,
        labels=labels,
        duckdb_connection=con,
        lookback_days=7,
        max_false_positive_rate=0.001,
    )
    # 1 FP / (999 TN + 1 FP) = 0.001 — not strictly below 0.1%
    assert validation.false_positive_rate == pytest.approx(0.001, abs=1e-9)
    assert validation.passed is False
    assert validation.block_reason == "false_positive_rate_exceeds_threshold"


def test_compute_fpr_zero_when_no_negatives_matched() -> None:
    cm = simulator.ConfusionMatrix(tp=2, fp=0, fn=0, tn=10)
    assert simulator.compute_false_positive_rate(cm) == 0.0
