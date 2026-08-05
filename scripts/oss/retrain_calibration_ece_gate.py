#!/usr/bin/env python3
"""ECE-gated Platt calibration retrain on joined y_labels (L3 ops loop).

Fit on chronological train window only; evaluate ECE/Brier on held-out report
window. Exit 1 when report ECE exceeds threshold unless --force (logged in artifact).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

_REPO = Path(__file__).resolve().parents[2]
_DEC_SRC = _REPO / "services" / "decision-api" / "src"
if str(_DEC_SRC) not in sys.path:
    sys.path.insert(0, str(_DEC_SRC))

from decision_api.reliability_export import score_for_binning  # noqa: E402

_SCHEMA_LABELS = "tarka.calibration_retrain_labels/v1"
_SCHEMA_CANDIDATE = "tarka.platt_calibration/v1"
_SCHEMA_ARTIFACT = "tarka.calibration_retrain_report/v1"


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    ex = math.exp(x)
    return ex / (1.0 + ex)


def apply_platt(score: float, a: float, b: float) -> float:
    return _sigmoid(a * score + b)


def fit_platt(scores: Sequence[float], labels: Sequence[int], *, max_iter: int = 100) -> tuple[float, float]:
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


def _parse_ts(raw: Any) -> datetime:
    text = str(raw or "").strip()
    if not text:
        return datetime.min.replace(tzinfo=UTC)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _row_score(row: dict[str, Any]) -> float | None:
    mapped = {
        "integrity_confidence": str(row.get("integrity_confidence") or row.get("score") or ""),
        "score": str(row.get("score") or row.get("integrity_confidence") or ""),
    }
    return score_for_binning(mapped)


def _row_label(row: dict[str, Any]) -> int | None:
    y = str(row.get("y_label") or "").strip()
    if y == "1":
        return 1
    if y == "0":
        return 0
    return None


def load_labeled_rows(path: Path) -> list[dict[str, Any]]:
    """Load labeled rows from JSON (reliability-export shape + y_label)."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        rows = raw
    elif isinstance(raw, dict):
        rows = raw.get("rows") or raw.get("labeled_rows") or []
    else:
        raise ValueError("labels file must be JSON object or array")
    if not isinstance(rows, list):
        raise ValueError("labels rows must be a list")
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        score = _row_score(row)
        label = _row_label(row)
        if score is None or label is None:
            continue
        out.append(
            {
                "created_at": row.get("created_at") or row.get("ts") or "",
                "score": score,
                "y_label": label,
                "trace_id": str(row.get("trace_id") or ""),
            }
        )
    if not out:
        raise ValueError("no labeled rows with score + y_label")
    out.sort(key=lambda r: _parse_ts(r["created_at"]))
    return out


def split_train_report(
    rows: Sequence[dict[str, Any]],
    *,
    train_end: str | None,
    train_fraction: float | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if train_end and train_fraction is not None:
        raise ValueError("use only one of train_end or train_fraction")
    if train_end:
        boundary = _parse_ts(train_end)
        train = [r for r in rows if _parse_ts(r["created_at"]) <= boundary]
        report = [r for r in rows if _parse_ts(r["created_at"]) > boundary]
        meta = {"split": "train_end", "train_end": boundary.isoformat()}
    elif train_fraction is not None:
        if not 0.0 < train_fraction < 1.0:
            raise ValueError("train_fraction must be in (0, 1)")
        cut = max(1, min(len(rows) - 1, int(len(rows) * train_fraction)))
        train = list(rows[:cut])
        report = list(rows[cut:])
        meta = {"split": "train_fraction", "train_fraction": train_fraction, "train_rows": cut}
    else:
        raise ValueError("train_end or train_fraction required")
    if not train or not report:
        raise ValueError("train and report windows must both be non-empty")
    return train, report, meta


def retrain(
    rows: Sequence[dict[str, Any]],
    *,
    train_end: str | None,
    train_fraction: float | None,
    ece_threshold: float,
    force: bool,
) -> dict[str, Any]:
    train, report, split_meta = split_train_report(
        rows, train_end=train_end, train_fraction=train_fraction
    )
    train_scores = [float(r["score"]) for r in train]
    train_labels = [int(r["y_label"]) for r in train]
    a, b = fit_platt(train_scores, train_labels)

    report_probs = [apply_platt(float(r["score"]), a, b) for r in report]
    report_labels = [int(r["y_label"]) for r in report]
    ece = expected_calibration_error(report_probs, report_labels)
    brier = brier_score(report_probs, report_labels)
    gate_passed = ece <= ece_threshold
    should_write = gate_passed or force

    return {
        "split_meta": split_meta,
        "platt": {"A": round(a, 8), "B": round(b, 8)},
        "train_rows": len(train),
        "report_rows": len(report),
        "ece": round(ece, 6),
        "brier": round(brier, 6),
        "ece_threshold": ece_threshold,
        "gate_passed": gate_passed,
        "should_write": should_write,
        "force": force,
    }


def build_candidate(result: dict[str, Any]) -> dict[str, Any]:
    platt = result["platt"]
    return {
        "schema_id": _SCHEMA_CANDIDATE,
        "method": "platt",
        "A": platt["A"],
        "B": platt["B"],
        "trained_at": datetime.now(tz=UTC).isoformat(),
        "train_rows": result["train_rows"],
        "report_rows": result["report_rows"],
        "fit_window": result["split_meta"],
    }


def build_artifact(result: dict[str, Any], *, candidate_written: bool) -> dict[str, Any]:
    return {
        "schema_id": _SCHEMA_ARTIFACT,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "ece": result["ece"],
        "brier": result["brier"],
        "ece_threshold": result["ece_threshold"],
        "gate_passed": result["gate_passed"],
        "force": bool(result["force"]),
        "candidate_written": candidate_written,
        "train_rows": result["train_rows"],
        "report_rows": result["report_rows"],
        "fit_window": result["split_meta"],
        "platt": result["platt"],
    }


def run(
    *,
    labels_path: Path,
    out_path: Path,
    artifact_path: Path,
    train_end: str | None,
    train_fraction: float | None,
    ece_threshold: float,
    force: bool,
) -> int:
    rows = load_labeled_rows(labels_path)
    result = retrain(
        rows,
        train_end=train_end,
        train_fraction=train_fraction,
        ece_threshold=ece_threshold,
        force=force,
    )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)

    if result["should_write"]:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(build_candidate(result), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        candidate_written = True
    else:
        candidate_written = False

    artifact_path.write_text(
        json.dumps(
            build_artifact(result, candidate_written=candidate_written),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    if not result["should_write"]:
        print(
            f"retrain_calibration_ece_gate: FAIL ece={result['ece']:.4f} "
            f"> threshold={ece_threshold}; candidate not written",
            file=sys.stderr,
        )
        return 1

    note = " (forced)" if result["force"] and not result["gate_passed"] else ""
    print(
        f"retrain_calibration_ece_gate: OK ece={result['ece']:.4f} "
        f"brier={result['brier']:.4f}{note} -> {out_path}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, required=True, help="Labeled rows JSON")
    parser.add_argument("--out", type=Path, required=True, help="Platt candidate JSON")
    parser.add_argument("--artifact-out", type=Path, required=True, help="Retrain report JSON")
    split = parser.add_mutually_exclusive_group(required=True)
    split.add_argument("--train-end", help="ISO timestamp; train rows created_at <= train-end")
    split.add_argument("--train-fraction", type=float, help="Chronological train fraction in (0,1)")
    parser.add_argument("--ece-threshold", type=float, default=0.05, help="Max report ECE (default 0.05)")
    parser.add_argument("--force", action="store_true", help="Write candidate even when ECE fails")
    args = parser.parse_args(argv)
    return run(
        labels_path=args.labels,
        out_path=args.out,
        artifact_path=args.artifact_out,
        train_end=args.train_end,
        train_fraction=args.train_fraction,
        ece_threshold=args.ece_threshold,
        force=args.force,
    )


if __name__ == "__main__":
    raise SystemExit(main())
