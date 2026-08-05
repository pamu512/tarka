"""Platt scaling fit/apply and calibration metrics (ECE, Brier)."""

from __future__ import annotations

import math
from typing import Sequence


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    ex = math.exp(x)
    return ex / (1.0 + ex)


def apply_platt(score: float, a: float, b: float) -> float:
    return _sigmoid(a * score + b)


def fit_platt(
    scores: Sequence[float],
    labels: Sequence[int],
    *,
    max_iter: int = 100,
) -> tuple[float, float]:
    """Logistic calibration on raw scores (Platt scaling, Newton steps)."""
    if len(scores) != len(labels) or not scores:
        raise ValueError("scores and labels must be same non-empty length")
    a, b = 1.0, 0.0
    for _ in range(max_iter):
        g_a = g_b = 0.0
        h_aa = h_ab = h_bb = 0.0
        for s, y in zip(scores, labels):
            p = apply_platt(s, a, b)
            w = p * (1.0 - p)
            err = p - float(y)
            g_a += err * s
            g_b += err
            h_aa += w * s * s
            h_ab += w * s
            h_bb += w
        det = h_aa * h_bb - h_ab * h_ab
        if det <= 1e-12:
            break
        da = (h_bb * g_a - h_ab * g_b) / det
        db = (-h_ab * g_a + h_aa * g_b) / det
        a -= da
        b -= db
        if abs(da) < 1e-9 and abs(db) < 1e-9:
            break
    return a, b


def expected_calibration_error(
    probs: Sequence[float],
    labels: Sequence[int],
    *,
    n_bins: int = 10,
) -> float:
    if len(probs) != len(labels):
        raise ValueError("probs and labels length mismatch")
    n = len(probs)
    if n == 0:
        return 0.0
    width = 1.0 / n_bins
    ece = 0.0
    for i in range(n_bins):
        lo = i * width
        hi = 1.0 if i == n_bins - 1 else (i + 1) * width
        idxs = [
            j
            for j, p in enumerate(probs)
            if (lo <= p < hi) or (i == n_bins - 1 and p == 1.0)
        ]
        if not idxs:
            continue
        conf = sum(probs[j] for j in idxs) / len(idxs)
        acc = sum(labels[j] for j in idxs) / len(idxs)
        ece += abs(acc - conf) * len(idxs) / n
    return ece


def brier_score(probs: Sequence[float], labels: Sequence[int]) -> float:
    if len(probs) != len(labels) or not probs:
        return 0.0
    return sum((float(p) - float(y)) ** 2 for p, y in zip(probs, labels)) / len(probs)
