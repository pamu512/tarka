from datetime import datetime, timedelta, timezone

from decision_api.calibration_window import (
    apply_window_override,
    calibration_window,
    can_override_calibration_window,
)
from decision_api.leftover_promote_gate import _desk_promote_from_parts


NOW = datetime(2026, 9, 6, tzinfo=timezone.utc)
GREEN = {"promote_allowed": True, "blockers": []}


def test_zero_labels_blocks_window():
    row = calibration_window(
        first_label_at=None, label_count=0, fp_rate=None, now=NOW
    )
    assert row["ok"] is False
    assert "window_open" in row["blockers"]
    assert "thin_labels" in row["blockers"]
    assert row["min_days"] == 7
    assert row["min_labels"] == 20
    assert row["max_fp"] == 0.05


def test_warm_window_ok():
    first = NOW - timedelta(days=7)
    row = calibration_window(
        first_label_at=first, label_count=20, fp_rate=0.01, now=NOW
    )
    assert row["ok"] is True
    assert row["blockers"] == []
    assert row["days"] == 7


def test_fp_above_cap_blocks_only_when_number():
    first = NOW - timedelta(days=10)
    hot = calibration_window(
        first_label_at=first, label_count=20, fp_rate=0.2, now=NOW
    )
    assert hot["ok"] is False
    assert hot["blockers"] == ["fp_above_cap"]
    missing = calibration_window(
        first_label_at=first, label_count=20, fp_rate=None, now=NOW
    )
    assert missing["ok"] is True


def test_desk_requires_calibration_window():
    window = calibration_window(
        first_label_at=None, label_count=0, fp_rate=None, now=NOW
    )
    desk = _desk_promote_from_parts(GREEN, GREEN, GREEN, GREEN, window)
    assert "calibration_window" in desk["requires"]
    assert desk["promote_allowed"] is False
    assert "window_open" in desk["blockers"]
    assert "thin_labels" in desk["blockers"]


def test_override_drops_only_window_blockers():
    window = calibration_window(
        first_label_at=None, label_count=0, fp_rate=None, now=NOW
    )
    leftover = {"promote_allowed": False, "blockers": ["leftover_sla_breached"]}
    desk = _desk_promote_from_parts(GREEN, GREEN, GREEN, leftover, window)
    assert can_override_calibration_window(["analyst"], "window still open") is False
    assert can_override_calibration_window(["RiskArchitect"], "short") is False
    out, applied = apply_window_override(
        desk,
        window,
        reason="window still open",
        roles=["RiskArchitect"],
    )
    assert applied is True
    assert "window_open" not in out["blockers"]
    assert "leftover_sla_breached" in out["blockers"]
    assert out["promote_allowed"] is False
