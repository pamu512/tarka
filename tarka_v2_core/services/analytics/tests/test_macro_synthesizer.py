"""Unit tests for macro synthesizer statistics (no ClickHouse)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from macro_synthesizer import (
    CASCADE_WINDOW_DAYS,
    DAILY_LOOKBACK_DAYS,
    HilOverrideRecord,
    HilOverrideType,
    MacroSynthesizer,
    _DailyRow,
    _scope_matches_calendar,
    _seasonal_slices,
    _window_statistics,
    compute_z_score,
)


def test_compute_z_score_handles_zero_sigma() -> None:
    z, sigma_used = compute_z_score(10.0, 5.0, 0.0)
    assert sigma_used == 1.0
    assert z == pytest.approx(5.0)


def test_window_statistics_90_day_window() -> None:
    anchor = date(2026, 6, 3)
    rows = [
        _DailyRow(
            day=anchor - timedelta(days=i),
            day_of_week=1,
            day_of_year=100,
            region_code="US-NY",
            tx_count=10,
            tx_volume_usd=float(100 + i),
            failed_auth_count=1 if i % 5 == 0 else 0,
        )
        for i in range(0, 90)
    ]
    stats = _window_statistics(rows, 90, anchor=anchor)
    assert stats.window_days == 90
    assert stats.sample_days == 90
    assert stats.total_tx_count == 10 * 90


def test_seasonal_slices_groups_by_year() -> None:
    anchor = date(2026, 6, 3)
    dow = int(anchor.isoweekday())
    doy = int(anchor.timetuple().tm_yday)
    rows = [
        _DailyRow(
            day=date(2024, 6, 3),
            day_of_week=dow,
            day_of_year=doy,
            region_code="US-NY",
            tx_count=5,
            tx_volume_usd=50.0,
            failed_auth_count=0,
        ),
        _DailyRow(
            day=date(2025, 6, 3),
            day_of_week=dow,
            day_of_year=doy,
            region_code="US-NY",
            tx_count=7,
            tx_volume_usd=70.0,
            failed_auth_count=1,
        ),
    ]
    seasonal = _seasonal_slices(rows, day_of_year=doy, day_of_week=dow, anchor=anchor)
    assert len(seasonal.slices) == 2
    assert {s.calendar_year for s in seasonal.slices} == {2024, 2025}


def test_cascade_window_days_order() -> None:
    assert CASCADE_WINDOW_DAYS == (1, 3, 7, 15, 30, 45, 60, 90)


def test_daily_lookback_covers_seasonal_plane() -> None:
    assert DAILY_LOOKBACK_DAYS >= 90 + (3 * 366)


def test_window_statistics_one_day_inclusive() -> None:
    anchor = date(2026, 6, 3)
    rows = [
        _DailyRow(
            day=anchor,
            day_of_week=1,
            day_of_year=154,
            region_code="",
            tx_count=3,
            tx_volume_usd=30.0,
            failed_auth_count=0,
        )
    ]
    stats = _window_statistics(rows, 1, anchor=anchor)
    assert stats.sample_days == 1
    assert stats.tx_volume_mean == pytest.approx(30.0)


def test_scope_matches_calendar_for_seasonal_exclusion() -> None:
    doy = 154
    dow = 2
    assert _scope_matches_calendar(f"day_of_year:{doy}", day_of_year=doy, day_of_week=dow, region_code="")
    assert not _scope_matches_calendar("day_of_year:999", day_of_year=doy, day_of_week=dow, region_code="")


def test_observed_24h_prefers_tactical_buckets() -> None:
    anchor_dt = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)
    anchor = anchor_dt.date()
    vol, fail = MacroSynthesizer._observed_24h_metrics(
        daily_rows=[
            _DailyRow(
                day=anchor,
                day_of_week=2,
                day_of_year=154,
                region_code="",
                tx_count=1,
                tx_volume_usd=999.0,
                failed_auth_count=9,
            )
        ],
        tactical=[],
        anchor=anchor,
        anchor_dt=anchor_dt,
    )
    assert vol == pytest.approx(999.0)
    assert fail == pytest.approx(9.0)


def test_hil_exclusions_only_allow_seasonal_with_scope() -> None:
    doy = 154
    dow = 2
    hil_all = [
        HilOverrideRecord(
            override_type=HilOverrideType.ALLOW_SEASONAL_SPIKE,
            scope_key=f"day_of_year:{doy}",
            expires_at=datetime(2027, 1, 1, tzinfo=UTC),
            analyst_rationale="holiday verified",
        ),
        HilOverrideRecord(
            override_type=HilOverrideType.FORCE_BLOCK,
            scope_key="global",
            expires_at=datetime(2027, 1, 1, tzinfo=UTC),
            analyst_rationale="manual block",
        ),
    ]
    exclusions = [
        r
        for r in hil_all
        if r.override_type == HilOverrideType.ALLOW_SEASONAL_SPIKE
        and _scope_matches_calendar(
            r.scope_key, day_of_year=doy, day_of_week=dow, region_code=""
        )
    ]
    assert len(exclusions) == 1
    assert len(hil_all) == 2
