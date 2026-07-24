"""Phase 4: ECE/Brier calibration helpers."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from decision_api.calibration_metrics import (
    brier_score,
    expected_calibration_error,
    report_calibration,
)


def test_perfect_calibration_has_zero_ece() -> None:
    # Bin edges for n_bins=2: [0,0.5) and [0.5,1]; match mean confidence to accuracy.
    scores = [0.0, 0.0, 1.0, 1.0]
    labels = [0, 0, 1, 1]
    assert expected_calibration_error(scores, labels, n_bins=2) == 0.0
    assert brier_score(scores, labels) == 0.0


def test_report_calibration_shape() -> None:
    out = report_calibration([0.2, 0.8], [0, 1], n_bins=2)
    assert out["n"] == 2
    assert 0.0 <= float(out["ece"]) <= 1.0
    assert 0.0 <= float(out["brier"]) <= 1.0
