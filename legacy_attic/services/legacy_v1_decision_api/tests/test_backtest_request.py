"""Backtest HTTP request model (window + rule pack wiring)."""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from pydantic import ValidationError

from decision_api.backtest_api import BacktestRequest, _window_bounds


def test_window_legacy_end_only() -> None:
    end = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    req = BacktestRequest(
        tenant_id="demo",
        end_time=end,
        rule_pack={
            "name": "p",
            "rules": [{"id": "r1", "when": [], "score_delta": 1.0}],
        },
    )
    start_s, end_s = _window_bounds(req)
    assert end_s == "2025-06-15 12:00:00"
    assert start_s == "2025-03-17 12:00:00"


def test_window_explicit_start_end_ok() -> None:
    st = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    en = datetime(2025, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
    req = BacktestRequest(
        tenant_id="demo",
        start_time=st,
        end_time=en,
        rule_pack={
            "name": "p",
            "rules": [{"id": "r1", "when": [], "score_delta": 1.0}],
        },
    )
    start_s, end_s = _window_bounds(req)
    assert start_s.startswith("2025-01-01")
    assert end_s.startswith("2025-03-01")


def test_window_rejects_over_90_days() -> None:
    st = datetime(2025, 1, 1, tzinfo=timezone.utc)
    en = st + timedelta(days=91)
    with pytest.raises(ValidationError):
        BacktestRequest(
            tenant_id="demo",
            start_time=st,
            end_time=en,
            rule_pack={
                "name": "p",
                "rules": [{"id": "r1", "when": [], "score_delta": 1.0}],
            },
        )


def test_window_accepts_exactly_90_days() -> None:
    st = datetime(2025, 1, 1, tzinfo=timezone.utc)
    en = st + timedelta(days=90)
    req = BacktestRequest(
        tenant_id="demo",
        start_time=st,
        end_time=en,
        rule_pack={
            "name": "p",
            "rules": [{"id": "r1", "when": [], "score_delta": 1.0}],
        },
    )
    start_s, end_s = _window_bounds(req)
    assert start_s.startswith("2025-01-01")
    assert end_s.startswith("2025-04-01")


def test_start_without_end_rejected() -> None:
    with pytest.raises(ValidationError):
        BacktestRequest(
            tenant_id="demo",
            start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
            rule_pack={
                "name": "p",
                "rules": [{"id": "r1", "when": [], "score_delta": 1.0}],
            },
        )
