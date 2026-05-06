from __future__ import annotations

"""Standardized evaluation metrics for graph benchmark harness (#64)."""


def _as_binary_labels(y: list[int]) -> list[int]:
    return [1 if int(x) >= 1 else 0 for x in y]


def precision_recall(
    y_true: list[int], y_score: list[float], *, threshold: float = 0.5
) -> tuple[float, float]:
    yt = _as_binary_labels(y_true)
    yp = [1 if float(s) >= threshold else 0 for s in y_score]
    tp = sum(1 for a, b in zip(yt, yp, strict=False) if a == 1 and b == 1)
    fp = sum(1 for a, b in zip(yt, yp, strict=False) if a == 0 and b == 1)
    fn = sum(1 for a, b in zip(yt, yp, strict=False) if a == 1 and b == 0)
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    return round(prec, 6), round(rec, 6)


def average_precision_binary(y_true: list[int], y_score: list[float]) -> float:
    """Average precision (binary), ranking by descending score."""
    pairs = sorted(zip(y_score, _as_binary_labels(y_true), strict=False), key=lambda x: -x[0])
    pos = sum(lab for _, lab in pairs)
    if pos == 0:
        return 0.0
    tp = 0
    ap = 0.0
    for i, (_, lab) in enumerate(pairs, start=1):
        if lab == 1:
            tp += 1
            ap += tp / i
    return round(float(ap / pos), 6)
