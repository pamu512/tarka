"""Join analyst / chargeback ground-truth labels onto reliability export rows."""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Sequence


def y_label_from_ground_truth(ground_truth_class: str | None) -> str:
    """Map FRAUD/LEGITIMATE (and common aliases) to binary y_label."""
    token = (ground_truth_class or "").strip().upper()
    if token in {"FRAUD", "1", "TRUE", "POSITIVE", "RESOLVED_FRAUD"}:
        return "1"
    if token in {"LEGITIMATE", "LEGIT", "0", "FALSE", "NEGATIVE", "RESOLVED_LEGIT"}:
        return "0"
    return ""


def apply_y_labels(
    export_rows: Sequence[MutableMapping[str, str]],
    labels_by_trace: Mapping[str, str],
    *,
    labels_by_entity: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Fill ``y_label`` on export rows. Prefer trace_id; fall back to entity_id.

    ``labels_by_*`` values must already be ``\"0\"`` / ``\"1\"`` (use
    :func:`y_label_from_ground_truth`).
    """
    by_entity = labels_by_entity or {}
    joined = 0
    for row in export_rows:
        if (row.get("y_label") or "").strip() in {"0", "1"}:
            joined += 1
            continue
        tid = (row.get("trace_id") or "").strip()
        if tid and tid in labels_by_trace:
            row["y_label"] = labels_by_trace[tid]
            joined += 1
            continue
        eid = (row.get("entity_id") or "").strip()
        if eid and eid in by_entity:
            row["y_label"] = by_entity[eid]
            joined += 1
    n = len(export_rows)
    coverage = (joined / n) if n else 0.0
    return {
        "rows": n,
        "y_label_joined": joined,
        "label_coverage": round(coverage, 4),
    }


def label_coverage_posture(
    *,
    label_coverage: float,
    min_coverage: float = 0.2,
    proxy_only: bool = False,
) -> dict[str, Any]:
    """Ops gate: calibration cannot report healthy when labels are missing."""
    if proxy_only or label_coverage < min_coverage:
        return {
            "healthy": False,
            "status": "insufficient_labels",
            "label_coverage": label_coverage,
            "min_coverage": min_coverage,
            "hint": "Join case dispositions / chargebacks into y_label before trusting reliability.",
        }
    return {
        "healthy": True,
        "status": "ok",
        "label_coverage": label_coverage,
        "min_coverage": min_coverage,
        "hint": "ok",
    }
