"""Unit tests: review-ring summary, listing id resolution, optional DuckDB signup burst."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ingestor.schemas import TransactionSchema  # noqa: E402
from shadow_agent.graph_hints import listing_id_from_transaction  # noqa: E402
from shadow_agent.review_integrity_tool import (  # noqa: E402
    _duckdb_same_10min_window,
    format_review_ring_summary,
    wants_check_review_integrity,
)


def test_listing_id_from_transaction_keys() -> None:
    tx = TransactionSchema(
        entity_id=UUID("11111111-1111-1111-1111-111111111111"),
        amount=1.0,
        timestamp=datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC),
        metadata={"review_listing_id": "L-42"},
    )
    assert listing_id_from_transaction(tx) == "L-42"


def test_wants_check_review_integrity_respects_preloaded_context() -> None:
    tx = TransactionSchema(
        entity_id=UUID("22222222-2222-2222-2222-222222222222"),
        amount=1.0,
        timestamp=datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC),
        metadata={"listing_id": "L-9"},
    )
    assert wants_check_review_integrity(tx, None) is True
    assert wants_check_review_integrity(tx, {"check_review_integrity": {"x": 1}}) is False


def test_format_review_ring_summary_high_risk_line() -> None:
    s = format_review_ring_summary(
        reviewer_count=5,
        hardware_overlap_count=4,
        hardware_kind="a hardware hash (shared Device)",
        same_10min_burst=True,
    )
    assert "4 out of 5" in s
    assert "hardware hash" in s
    assert "10-minute burst" in s


def test_duckdb_same_10min_window_true(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("duckdb")
    import duckdb

    db_path = tmp_path / "signups.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE user_signups (user_id VARCHAR, created_at TIMESTAMP)")
    t0 = datetime(2026, 5, 1, 10, 0, 0, tzinfo=UTC)
    for i, uid in enumerate(("a", "b", "c")):
        con.execute(
            "INSERT INTO user_signups VALUES (?, ?)",
            [uid, t0 + timedelta(minutes=i)],
        )
    con.close()

    monkeypatch.setenv("SHADOW_SIGNUPS_DUCKDB_PATH", str(db_path))
    out = _duckdb_same_10min_window(["a", "b", "c"])
    assert out.get("all_reviewers_same_10min_window") is True
    assert out.get("signup_span_seconds") == 120.0
