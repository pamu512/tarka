"""Gate (Prompt 194): Scout coordinated burst detection on DuckDB raw_signals."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from shadow_agent.schemas import HypothesisReport  # noqa: E402
from shadow_agent.scout_coordinated_burst import (  # noqa: E402
    format_burst_narrative,
    scan_coordinated_bursts,
    scout_coordinated_burst_mode,
    suggested_shadow_rule,
)


def _seed_burst_db(db_path: Path, *, shared_canvas: str, account_count: int) -> None:
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
    base = datetime(2026, 5, 18, 12, 0, 0, tzinfo=UTC)
    rows = []
    for i in range(account_count):
        ts = base + timedelta(minutes=i * 10)
        acc = f"acc_{i:02d}"
        payload = {
            "ch": shared_canvas,
            "wv": f"vendor-{i}",
            "sid": f"sess-{i}",
            "metadata": {"acc_id": acc},
        }
        rows.append(
            (
                ts.replace(tzinfo=None),
                f"sess-{i}",
                json.dumps(payload, separators=(",", ":")),
                i + 1,
            ),
        )
    con.executemany(
        "INSERT INTO raw_signals VALUES (?, ?, ?, ?)",
        rows,
    )
    con.close()


def test_scout_finds_canvas_burst_and_emits_hypothesis_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHADOW_SCOUT_BACKTEST_GATE", "off")
    db = tmp_path / "signals.duckdb"
    canvas = "canvas_hash_999_xyz"
    _seed_burst_db(db, shared_canvas=canvas, account_count=7)
    out = scan_coordinated_bursts(
        duckdb_path_override=str(db),
        min_distinct_accounts=6,
        window_hours=4,
        lookback_hours=48,
    )
    assert out.get("error") is None
    assert out["bursts_found"] >= 1
    reports = out["hypothesis_reports"]
    assert isinstance(reports, list) and reports
    validated = HypothesisReport.model_validate(reports[0])
    assert validated.fingerprint_kind == "canvas_hash"
    assert validated.fingerprint_value == canvas
    assert validated.distinct_account_count >= 6
    assert len(validated.account_ids) >= 6
    assert validated.suggested_rule is not None
    assert validated.suggested_rule["metadata"]["is_shadow"] is True


def test_scout_no_burst_below_threshold(tmp_path: Path) -> None:
    db = tmp_path / "quiet.duckdb"
    _seed_burst_db(db, shared_canvas="unique_canvas", account_count=3)
    out = scan_coordinated_bursts(
        duckdb_path_override=str(db),
        min_distinct_accounts=6,
        window_hours=4,
    )
    assert out.get("error") is None
    assert out["bursts_found"] == 0
    assert out["hypothesis_reports"] == []


def test_format_narrative_and_suggested_rule() -> None:
    ws = datetime(2026, 5, 18, 8, 0, tzinfo=UTC)
    we = datetime(2026, 5, 18, 12, 0, tzinfo=UTC)
    text = format_burst_narrative(
        fingerprint_kind="webgl_vendor",
        fingerprint_value="ANGLE",
        distinct_account_count=8,
        window_hours=4,
        window_start=ws,
        window_end=we,
    )
    assert "8 distinct accounts" in text
    assert "WebGL vendor" in text
    rule = suggested_shadow_rule(fingerprint_kind="canvas_hash", fingerprint_value="abc")
    assert rule["when"][0]["field"] == "canvas_hash"


def test_scout_mode_default_auto() -> None:
    assert scout_coordinated_burst_mode() == "auto"
