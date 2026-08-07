"""Tazama-class typology ops control plane (weights + breach policy; not ISO 20022)."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

from decision_api.typology import (
    evaluate_typologies,
    load_typology_definitions,
    summarize_typologies,
    weighted_aggregation_telemetry,
)


def aggregate_typology_breaches_from_audits(
    audits: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Histogram highest_breach / driver_typology from evaluate audit snapshots."""
    breach_counts: Counter[str] = Counter()
    driver_counts: Counter[str] = Counter()
    scanned = 0
    with_summary = 0
    for item in audits:
        if not isinstance(item, Mapping):
            continue
        scanned += 1
        snap = item.get("payload_snapshot")
        if not isinstance(snap, Mapping):
            continue
        summary = snap.get("typology_summary")
        if not isinstance(summary, Mapping):
            # Some rows nest under decision payload keys
            typologies = snap.get("typologies")
            if isinstance(typologies, list) and typologies:
                summary = summarize_typologies(
                    [t for t in typologies if isinstance(t, dict)]
                )
            else:
                continue
        with_summary += 1
        hb = str(summary.get("highest_breach") or "pass").strip().lower() or "pass"
        breach_counts[hb] += 1
        driver = summary.get("driver_typology_id")
        if driver:
            driver_counts[str(driver)] += 1
    return {
        "schema_id": "tarka.typology_breach_histogram/v1",
        "audits_scanned": scanned,
        "rows_with_typology_summary": with_summary,
        "highest_breach_counts": dict(breach_counts),
        "driver_typology_counts": dict(driver_counts.most_common(20)),
        "alert_or_warning_rows": int(breach_counts.get("alert", 0))
        + int(breach_counts.get("warning", 0)),
        "note": (
            "Audit-derived breach telemetry for typology ops — not a payment-switch "
            "processor fleet or ISO 20022 bus."
        ),
    }


def load_typology_ops_posture(
    *,
    sample_rule_hits: list[str] | None = None,
    sample_features: dict[str, Any] | None = None,
    audit_breach_histogram: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Ops surface: configured typologies + optional live evaluate sample + audit histogram."""
    telem = weighted_aggregation_telemetry()
    data = load_typology_definitions()
    hits = list(sample_rule_hits or [])
    feats = dict(sample_features or {})
    live_rows: list[dict[str, Any]] = []
    summary: dict[str, Any] | None = None
    if hits or feats:
        live_rows = evaluate_typologies(hits, feats)
        summary = summarize_typologies(live_rows)
        telem = weighted_aggregation_telemetry(live_rows)
    alert_ids = [
        c["id"]
        for c in telem.get("configured") or []
        if isinstance(c, dict) and c.get("id")
    ]
    hist = (
        dict(audit_breach_histogram)
        if isinstance(audit_breach_histogram, Mapping)
        else None
    )
    return {
        "schema_id": "tarka.typology_ops_posture/v1",
        "control_plane": {
            "aggregation": (telem.get("aggregation") or {}).get("mode"),
            "dsl_version": telem.get("dsl_version"),
            "predicate_registry": telem.get("predicate_registry"),
            "typology_count": telem.get("typology_count"),
        },
        "configured": telem.get("configured") or [],
        "live_scores": telem.get("live_scores") or [],
        "sample_summary": summary,
        "audit_breach_histogram": hist,
        "borrowed_from": "Tazama typology processor (weights + breach thresholds)",
        "vs_tazama": (
            "In-process typology DSL + ops telemetry — not OpenFaaS rule/typology "
            "processor fleet or ISO 20022 messaging."
        ),
        "honesty": (
            "Breach thresholds are productized here; bank/switch typology ops still "
            "thinner than Tazama."
        ),
        "definitions_path": "rules/typology_definitions_v1.json",
        "configured_ids": alert_ids,
        "definition_count": len(data.get("typologies") or []),
    }
