"""Per-vertical calibration / drift from fixture holdouts (honest about synthetic).

Best decision: surface reliability bins from labeled holdouts used for promote —
never claim LIVE calibration. No circular import with promote registry.
"""

from __future__ import annotations

from typing import Any

from decision_api.vertical_packs import get_vertical_pack

SCHEMA_ID = "tarka.vertical_calibration/v1"
METHOD = "holdout_reliability_v1"
_PRIORITY_VERTICALS = ("marketplace", "food_delivery", "e_hailing")
_DEFAULT_SCORE_THRESHOLD = 30.0


def _bins(scores: list[float], labels: list[int], n_bins: int = 10) -> list[dict[str, Any]]:
    if not scores:
        return []
    width = 100.0 / n_bins
    out: list[dict[str, Any]] = []
    for i in range(n_bins):
        lo = i * width
        hi = (i + 1) * width
        idxs = [
            j
            for j, s in enumerate(scores)
            if (s >= lo and s < hi) or (i == n_bins - 1 and s >= lo)
        ]
        if not idxs:
            out.append(
                {
                    "bin": i,
                    "lo": round(lo, 2),
                    "hi": round(hi, 2),
                    "n": 0,
                    "mean_score": None,
                    "positive_rate": None,
                }
            )
            continue
        mean_s = sum(scores[j] for j in idxs) / len(idxs)
        pos = sum(labels[j] for j in idxs) / len(idxs)
        out.append(
            {
                "bin": i,
                "lo": round(lo, 2),
                "hi": round(hi, 2),
                "n": len(idxs),
                "mean_score": round(mean_s, 4),
                "positive_rate": round(pos, 4),
            }
        )
    return out


def _ece(bins: list[dict[str, Any]]) -> float | None:
    total = sum(int(b["n"] or 0) for b in bins)
    if total <= 0:
        return None
    err = 0.0
    for b in bins:
        n = int(b["n"] or 0)
        if n <= 0 or b["mean_score"] is None or b["positive_rate"] is None:
            continue
        err += (n / total) * abs(float(b["mean_score"]) / 100.0 - float(b["positive_rate"]))
    return round(err, 6)


def _score_holdout(
    vertical: str,
    *,
    score_threshold: float = _DEFAULT_SCORE_THRESHOLD,
) -> tuple[list[float], list[int], list[int], dict[str, Any] | None]:
    """Return scores, labels, preds, pack-or-None. Lazy-import holdout loader."""
    from decision_api.vertical_promote_registry import _pack_score, load_holdout_rows

    pack = get_vertical_pack(vertical)
    rows = load_holdout_rows(vertical)
    if not pack or not rows:
        return [], [], [], pack
    rules = list(pack.get("rules") or [])
    scores: list[float] = []
    labels: list[int] = []
    preds: list[int] = []
    for row in rows:
        feats = dict(row.get("features") or {})
        y = row.get("y")
        if y is None:
            y = row.get("label")
        try:
            yi = int(y)
        except (TypeError, ValueError):
            continue
        if yi not in (0, 1):
            continue
        sc, _ = _pack_score(feats, rules)
        scores.append(sc)
        labels.append(yi)
        preds.append(1 if sc >= score_threshold else 0)
    return scores, labels, preds, pack


def _f1(y_true: list[int], y_pred: list[int]) -> float:
    tp = fp = fn = 0
    for yt, yp in zip(y_true, y_pred, strict=True):
        if yt == 1 and yp == 1:
            tp += 1
        elif yt == 0 and yp == 1:
            fp += 1
        elif yt == 1 and yp == 0:
            fn += 1
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    return (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0


def fixture_ece_snapshot(vertical: str) -> dict[str, Any]:
    """Lightweight ECE/drift for promote CI — no promote registry recursion."""
    scores, labels, preds, pack = _score_holdout(vertical)
    if not pack or not scores:
        return {
            "ok": False,
            "expected_calibration_error": None,
            "drift_flag": "unknown",
            "promote_f1": 0.0,
        }
    bins = _bins(scores, labels)
    ece = _ece(bins)
    f1 = _f1(labels, preds)
    drift = "ok"
    if ece is not None and ece >= 0.15 and f1 >= 0.5:
        drift = "elevated"
    if ece is not None and ece >= 0.25:
        drift = "critical"
    return {
        "ok": True,
        "expected_calibration_error": ece,
        "drift_flag": drift,
        "promote_f1": round(f1, 6),
        "n": len(scores),
        "reliability_bins": bins,
        "bin_count": len(bins),
        "populated_bin_count": sum(1 for b in bins if int(b.get("n") or 0) > 0),
    }


def calibrate_vertical(vertical: str) -> dict[str, Any]:
    scores, labels, preds, pack = _score_holdout(vertical)
    if not pack or not scores:
        return {
            "vertical": vertical,
            "schema_id": SCHEMA_ID,
            "method": METHOD,
            "ok": False,
            "blocker": "missing_pack_or_holdout",
            "live_calibration_claim_allowed": False,
            "fixture_calibration_only": True,
        }
    bins = _bins(scores, labels)
    snap = fixture_ece_snapshot(vertical)
    return {
        "vertical": vertical,
        "schema_id": SCHEMA_ID,
        "method": METHOD,
        "ok": True,
        "n": len(scores),
        "score_threshold": _DEFAULT_SCORE_THRESHOLD,
        "reliability_bins": bins,
        "expected_calibration_error": snap["expected_calibration_error"],
        "drift_flag": snap["drift_flag"],
        "promote_f1": snap["promote_f1"],
        "live_calibration_claim_allowed": False,
        "fixture_calibration_only": True,
        "label_source": "synthetic_holdout_jsonl",
        "honesty": "Fixture labels only — not tenant truth",
    }


def load_all_vertical_calibration_posture() -> dict[str, Any]:
    packs = [calibrate_vertical(v) for v in _PRIORITY_VERTICALS]
    return {
        "schema_id": SCHEMA_ID,
        "method": METHOD,
        "live_calibration_claim_allowed": False,
        "fixture_calibration_only": True,
        "verticals": packs,
        "any_drift_elevated": any(
            p.get("drift_flag") in ("elevated", "critical") for p in packs
        ),
    }
