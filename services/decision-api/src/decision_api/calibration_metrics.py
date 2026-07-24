"""Holdout calibration metrics (ECE / Brier) for score → probability reporting."""

from __future__ import annotations

from typing import Sequence


def expected_calibration_error(
    scores: Sequence[float],
    labels: Sequence[int],
    *,
    n_bins: int = 10,
) -> float:
    """ECE for scores in ``[0, 1]`` vs binary labels ``{0,1}``."""
    if not scores or len(scores) != len(labels) or n_bins < 1:
        return 0.0
    bins: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]
    for s, y in zip(scores, labels, strict=True):
        s_clamped = max(0.0, min(1.0, float(s)))
        idx = min(n_bins - 1, int(s_clamped * n_bins))
        bins[idx].append((s_clamped, int(y)))
    n = len(scores)
    ece = 0.0
    for bucket in bins:
        if not bucket:
            continue
        conf = sum(s for s, _ in bucket) / len(bucket)
        acc = sum(y for _, y in bucket) / len(bucket)
        ece += (len(bucket) / n) * abs(acc - conf)
    return ece


def brier_score(scores: Sequence[float], labels: Sequence[int]) -> float:
    if not scores or len(scores) != len(labels):
        return 0.0
    total = 0.0
    for s, y in zip(scores, labels, strict=True):
        p = max(0.0, min(1.0, float(s)))
        total += (p - int(y)) ** 2
    return total / len(scores)


def report_calibration(
    scores: Sequence[float],
    labels: Sequence[int],
    *,
    n_bins: int = 10,
) -> dict[str, float | int]:
    return {
        "n": len(scores),
        "n_bins": n_bins,
        "ece": expected_calibration_error(scores, labels, n_bins=n_bins),
        "brier": brier_score(scores, labels),
        "positive_rate": (sum(int(y) for y in labels) / len(labels)) if labels else 0.0,
    }
