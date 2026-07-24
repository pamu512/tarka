"""Champion/challenger experiment helpers with sample-size / power gates."""

from __future__ import annotations

import math
from typing import Any


def min_samples_for_proportion_diff(
    *,
    baseline_rate: float,
    mde: float,
    alpha: float = 0.05,
    power: float = 0.8,
) -> int:
    """Approximate two-proportion sample size per arm (normal approx)."""
    p = max(1e-6, min(1.0 - 1e-6, float(baseline_rate)))
    d = max(1e-6, abs(float(mde)))
    # z_alpha/2 ~ 1.96, z_beta ~ 0.84 for alpha=0.05 power=0.8
    z_a = 1.96 if abs(alpha - 0.05) < 1e-9 else 1.64485
    z_b = 0.841621 if abs(power - 0.8) < 1e-9 else 1.28155
    pooled_var = 2.0 * p * (1.0 - p)
    n = ((z_a + z_b) ** 2) * pooled_var / (d**2)
    return max(1, int(math.ceil(n)))


def experiment_rollout_gate(
    *,
    challenger_n: int,
    baseline_rate: float,
    observed_challenger_rate: float,
    mde: float = 0.02,
    fpr_budget: float | None = None,
) -> dict[str, Any]:
    """Return whether a challenger may promote given sample size and FPR budget."""
    need = min_samples_for_proportion_diff(baseline_rate=baseline_rate, mde=mde)
    enough = challenger_n >= need
    delta = float(observed_challenger_rate) - float(baseline_rate)
    within_fpr = True
    if fpr_budget is not None:
        within_fpr = float(observed_challenger_rate) <= float(fpr_budget)
    return {
        "min_samples_per_arm": need,
        "challenger_n": challenger_n,
        "sample_size_ok": enough,
        "rate_delta": delta,
        "within_fpr_budget": within_fpr,
        "promote_eligible": bool(enough and within_fpr and delta <= 0),
    }
