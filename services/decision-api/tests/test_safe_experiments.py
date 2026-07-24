"""Phase 4: champion/challenger sample-size gate."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from decision_api.safe_experiments import experiment_rollout_gate


def test_rollout_gate_blocks_undersampled_challenger() -> None:
    out = experiment_rollout_gate(
        challenger_n=10,
        baseline_rate=0.05,
        observed_challenger_rate=0.04,
        mde=0.02,
        fpr_budget=0.06,
    )
    assert out["sample_size_ok"] is False
    assert out["promote_eligible"] is False
