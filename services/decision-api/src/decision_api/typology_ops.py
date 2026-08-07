"""Tazama-class typology ops control plane (weights + breach policy; not ISO 20022)."""

from __future__ import annotations

from typing import Any

from decision_api.typology import (
    evaluate_typologies,
    load_typology_definitions,
    summarize_typologies,
    weighted_aggregation_telemetry,
)


def load_typology_ops_posture(
    *,
    sample_rule_hits: list[str] | None = None,
    sample_features: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ops surface: configured typologies + optional live evaluate sample."""
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
