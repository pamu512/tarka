"""Gate (Prompt 196): Scout only surfaces hypotheses that pass DuckDB FPR backtest."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import duckdb
import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import shadow_agent.scout_coordinated_burst as scout  # noqa: E402


def _seed_burst_db(db_path: Path) -> None:
    con = duckdb.connect(str(db_path))
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
    base = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2)
    canvas = "canvas_gate_scout"
    rows = []
    for i in range(7):
        rows.append(
            (
                base + timedelta(minutes=i * 10),
                f"sess-{i}",
                json.dumps({"ch": canvas, "px": False, "sid": f"sess-{i}", "metadata": {"acc_id": f"a{i}"}}),
                i + 1,
            ),
        )
    con.executemany("INSERT INTO raw_signals VALUES (?, ?, ?, ?)", rows)
    con.close()


def test_scout_blocks_hypothesis_when_backtest_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHADOW_SCOUT_BACKTEST_GATE", "auto")
    db = tmp_path / "scout_gate.duckdb"
    _seed_burst_db(db)

    def _fail_gate(*_a: object, **_k: object) -> dict:
        return {
            "passed": False,
            "false_positive_rate": 0.05,
            "lookback_days": 7,
            "max_false_positive_rate": 0.001,
            "analyst_suggestion_allowed": False,
            "block_reason": "false_positive_rate_exceeds_threshold",
            "confusion_matrix": {"tp": 0, "fp": 1, "fn": 0, "tn": 10},
            "population_users": 11,
            "matched_users": 1,
        }

    with patch(
        "shadow_agent.hypothesis_backtest_client.validate_suggested_rule_for_analyst",
        side_effect=_fail_gate,
    ):
        out = scout.scan_coordinated_bursts(duckdb_path_override=str(db), min_distinct_accounts=6)

    assert out["bursts_found"] >= 1
    assert out["hypothesis_reports"] == []
    assert len(out["hypothesis_reports_blocked"]) >= 1
    blocked = out["hypothesis_reports_blocked"][0]
    assert blocked.get("analyst_suggestion_allowed") is False
