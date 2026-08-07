"""Rule precision / FP proxy after y_label join (missed-mark bridge C3)."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from decision_api.label_join import label_coverage_posture


def _as_hits(raw: Any) -> list[str]:
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[str] = []
    for item in raw:
        token = str(item or "").strip()
        if token:
            out.append(token)
    return out


def rule_precision_after_labels(
    rows: Sequence[Mapping[str, Any]],
    *,
    min_labeled_hits: int = 5,
    min_coverage: float = 0.2,
) -> dict[str, Any]:
    """Per-rule precision using joined y_label (1=fraud, 0=legit).

    FP proxy: rule fired and decision was deny/review but y_label is legitimate (0).
    Precision: labeled fraud hits / labeled hits for that rule.
    """
    total = len(rows)
    labeled = 0
    per: dict[str, dict[str, int]] = {}
    for row in rows:
        y = str(row.get("y_label") or "").strip()
        if y not in {"0", "1"}:
            continue
        labeled += 1
        hits = _as_hits(row.get("rule_hits"))
        if not hits:
            continue
        decision = str(row.get("decision") or "").strip().lower()
        for rule_id in hits:
            bucket = per.setdefault(
                rule_id, {"labeled_hits": 0, "fraud_hits": 0, "fp_hits": 0}
            )
            bucket["labeled_hits"] += 1
            if y == "1":
                bucket["fraud_hits"] += 1
            elif decision in {"deny", "block", "review"}:
                bucket["fp_hits"] += 1

    coverage = (labeled / total) if total else 0.0
    posture = label_coverage_posture(
        label_coverage=coverage, min_coverage=min_coverage, proxy_only=False
    )
    rules: list[dict[str, Any]] = []
    for rule_id, b in per.items():
        n = int(b["labeled_hits"])
        fraud = int(b["fraud_hits"])
        fp = int(b["fp_hits"])
        precision = (fraud / n) if n else 0.0
        rules.append(
            {
                "rule_id": rule_id,
                "labeled_hits": n,
                "fraud_hits": fraud,
                "fp_hits": fp,
                "precision": round(precision, 4),
                "fp_rate": round((fp / n) if n else 0.0, 4),
                "enough_support": n >= min_labeled_hits,
            }
        )
    rules.sort(key=lambda r: (-int(r["labeled_hits"]), str(r["rule_id"])))
    return {
        "schema_id": "tarka.rule_precision_after_labels/v1",
        "rows_scanned": total,
        "labeled_rows": labeled,
        "label_coverage": round(coverage, 4),
        "min_labeled_hits": min_labeled_hits,
        "posture": posture,
        "rules": rules,
    }
