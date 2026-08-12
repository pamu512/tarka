"""EWMA baselines + window_rows builder (never invent)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def trend_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("TREND_AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TREND_AGENT_DB_NAME", "trend_win.sqlite3")
    monkeypatch.setenv("TREND_BASELINE_MIN_N", "3")
    from analytics import trend_store

    trend_store.reset_connection_for_tests()
    yield tmp_path
    trend_store.reset_connection_for_tests()


def test_insufficient_baseline_skips(trend_db: Path) -> None:
    from analytics.trend_windows import build_window_rows_or_none

    feats = {"event_count_5m": 10, "event_count_24h": 40}
    rows, meta = build_window_rows_or_none(
        tenant_id="t1", entity_id="e1", features=feats, record=True
    )
    assert rows is None
    assert meta["skip_reason"] == "insufficient_baseline"


def test_ready_after_min_n_ticks(trend_db: Path) -> None:
    from analytics.trend_windows import build_window_rows_or_none

    feats = {"event_count_5m": 10.0, "event_count_24h": 40.0}
    for i in range(3):
        rows, meta = build_window_rows_or_none(
            tenant_id="t1",
            entity_id="e1",
            features={**feats, "event_count_5m": 10.0 + i, "event_count_24h": 40.0 + i},
            record=True,
        )
        if i < 2:
            assert rows is None
            assert meta["skip_reason"] == "insufficient_baseline"
        else:
            # 3rd tick: prior n=2 not ready yet (min 3). Still skip.
            assert rows is None

    # 4th tick: prior n=3 ready → rows emitted
    rows, meta = build_window_rows_or_none(
        tenant_id="t1",
        entity_id="e1",
        features={"event_count_5m": 100.0, "event_count_24h": 200.0},
        record=True,
    )
    assert rows is not None
    assert len(rows) == 2
    assert all("baseline_mean" in r for r in rows)
    assert all(r["observed"] in (100.0, 200.0) for r in rows)


def test_watchlist_upsert_list(trend_db: Path) -> None:
    from analytics import trend_store

    trend_store.upsert_watch(tenant_id="t1", entity_id="e9", reason="shadow_high_risk")
    items = trend_store.list_watch(tenant_id="t1")
    assert len(items) == 1
    assert items[0]["entity_id"] == "e9"
