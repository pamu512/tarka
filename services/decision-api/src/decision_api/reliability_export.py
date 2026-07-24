"""Build reliability / calibration export rows from decision_audit (Wave 1 trust).

Offline notebooks join ``y_label`` from case dispositions. When labels are absent,
``proxy_label_from_decision`` maps block/review-style decisions to 1 and allow-like
to 0 so operators can still sketch a reliability curve with an explicit caveat.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Iterable, Mapping, Sequence

RELIABILITY_CSV_FIELDS: tuple[str, ...] = (
    "trace_id",
    "tenant_id",
    "entity_id",
    "event_type",
    "decision",
    "score",
    "integrity_confidence",
    "confidence_tier",
    "calibration_profile",
    "expected_calibration_version",
    "y_label",
    "proxy_label_from_decision",
    "created_at",
)

_POSITIVE_DECISIONS = frozenset(
    {
        "block",
        "deny",
        "reject",
        "fraud",
        "review",
        "challenge",
        "step_up",
        "decline",
    }
)
_NEGATIVE_DECISIONS = frozenset(
    {
        "allow",
        "approve",
        "pass",
        "legit",
        "accept",
    }
)


def inference_from_payload(payload_snapshot: Any) -> dict[str, Any]:
    if not isinstance(payload_snapshot, dict):
        return {}
    inf = payload_snapshot.get("inference_context")
    return inf if isinstance(inf, dict) else {}


def proxy_label_from_decision(decision: str | None) -> str:
    """Return '1', '0', or '' when the decision string is ambiguous."""
    d = (decision or "").strip().lower()
    if d in _POSITIVE_DECISIONS:
        return "1"
    if d in _NEGATIVE_DECISIONS:
        return "0"
    return ""


def audit_row_to_export_dict(row: Mapping[str, Any]) -> dict[str, str]:
    """Normalize an audit mapping (SQLAlchemy row or dict) into CSV fields."""
    inf = inference_from_payload(row.get("payload_snapshot"))
    decision = str(row.get("decision") or "")
    created = row.get("created_at")
    if created is not None and hasattr(created, "isoformat"):
        created_s = created.isoformat()
    else:
        created_s = str(created or "")
    trace = row.get("trace_id")
    return {
        "trace_id": str(trace) if trace is not None else "",
        "tenant_id": str(row.get("tenant_id") or ""),
        "entity_id": str(row.get("entity_id") or ""),
        "event_type": str(row.get("event_type") or ""),
        "decision": decision,
        "score": "" if row.get("score") is None else str(row.get("score")),
        "integrity_confidence": (
            ""
            if inf.get("integrity_confidence") is None
            else str(inf.get("integrity_confidence"))
        ),
        "confidence_tier": str(inf.get("confidence_tier") or ""),
        "calibration_profile": str(inf.get("calibration_profile") or ""),
        "expected_calibration_version": (
            ""
            if inf.get("expected_calibration_version") is None
            else str(inf.get("expected_calibration_version"))
        ),
        "y_label": "",
        "proxy_label_from_decision": proxy_label_from_decision(decision),
        "created_at": created_s,
    }


def rows_to_csv(rows: Iterable[Mapping[str, Any]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(RELIABILITY_CSV_FIELDS))
    writer.writeheader()
    for row in rows:
        writer.writerow(audit_row_to_export_dict(row))
    return buf.getvalue()


def score_for_binning(export_row: Mapping[str, str]) -> float | None:
    """Prefer integrity_confidence in [0,1]; else normalize score assuming 0–100."""
    raw_ic = (export_row.get("integrity_confidence") or "").strip()
    if raw_ic:
        try:
            v = float(raw_ic)
        except ValueError:
            v = None
        else:
            if 0.0 <= v <= 1.0:
                return v
            if 0.0 <= v <= 100.0:
                return v / 100.0
    raw_score = (export_row.get("score") or "").strip()
    if not raw_score:
        return None
    try:
        s = float(raw_score)
    except ValueError:
        return None
    if 0.0 <= s <= 1.0:
        return s
    if 0.0 <= s <= 100.0:
        return s / 100.0
    return None


def reliability_bins(
    export_rows: Sequence[Mapping[str, str]],
    *,
    n_bins: int = 10,
    use_proxy_labels: bool = True,
) -> dict[str, Any]:
    """Equal-width bins on [0,1] vs binary labels. Empty y_label falls back to proxy."""
    if n_bins < 2 or n_bins > 50:
        raise ValueError("n_bins must be between 2 and 50")
    width = 1.0 / n_bins
    bins: list[dict[str, Any]] = []
    for i in range(n_bins):
        lo = i * width
        hi = 1.0 if i == n_bins - 1 else (i + 1) * width
        bins.append(
            {
                "bin_index": i,
                "lo": round(lo, 4),
                "hi": round(hi, 4),
                "n": 0,
                "n_positive": 0,
                "mean_score": None,
                "positive_rate": None,
            }
        )

    labeled = 0
    proxy_used = 0
    sums = [0.0] * n_bins
    for raw in export_rows:
        score = score_for_binning(raw)
        if score is None:
            continue
        y = (raw.get("y_label") or "").strip()
        if y in {"0", "1"}:
            label = int(y)
        elif use_proxy_labels:
            p = (raw.get("proxy_label_from_decision") or "").strip()
            if p not in {"0", "1"}:
                continue
            label = int(p)
            proxy_used += 1
        else:
            continue
        labeled += 1
        idx = min(int(score / width), n_bins - 1) if score < 1.0 else n_bins - 1
        bins[idx]["n"] += 1
        bins[idx]["n_positive"] += label
        sums[idx] += score

    for i, b in enumerate(bins):
        n = int(b["n"])
        if n <= 0:
            continue
        b["mean_score"] = round(sums[i] / n, 4)
        b["positive_rate"] = round(int(b["n_positive"]) / n, 4)

    return {
        "schema_id": "tarka.reliability_bins/v1",
        "n_bins": n_bins,
        "labeled_rows": labeled,
        "proxy_label_rows": proxy_used,
        "label_source": (
            "proxy_from_decision"
            if proxy_used and proxy_used == labeled
            else ("mixed" if proxy_used else "y_label")
        ),
        "caveat": (
            "proxy_label_from_decision is not ground truth; join case dispositions "
            "into y_label for true reliability diagrams."
            if proxy_used
            else None
        ),
        "bins": bins,
    }


def parse_inference_json_cell(raw: Any) -> dict[str, Any]:
    """Used by the CLI export script when SQL returns inference JSON separately."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}
    return {}
