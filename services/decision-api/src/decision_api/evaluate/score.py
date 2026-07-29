"""Score / fallback helpers for the evaluate pipeline."""

from __future__ import annotations

from typing import Any

from decision_api.config import settings

_SIGNAL_UNAVAILABLE_AUDIT: dict[str, str] = {
    "lists:unavailable": "Signal Entity lists was unavailable",
    "graph:unavailable": "Signal Graph risk was unavailable",
    "enrichment:unavailable": "Signal Feature enrichment was unavailable",
    "ml:unavailable": "Signal ML scoring was unavailable",
    "opa:unavailable": "Signal Policy (OPA) was unavailable",
    "calibration:unavailable": "Signal Calibration was unavailable",
    "counter:unavailable": "Signal Counter service was unavailable",
    "location:unavailable": "Signal Location intelligence was unavailable",
    "redis:tag_merge_unavailable": "Signal Redis tag merge was unavailable",
    "redis:tenant_flags_unavailable": "Signal Redis tenant flags was unavailable",
    "redis:entity_tags_unavailable": "Signal Redis entity tags was unavailable",
    "consortium:unavailable": "Signal Consortium cross-tenant signal was unavailable",
    "async_osint:unavailable": "Signal Async OSINT cache was unavailable",
    "async_enrich:stale": "Async OSINT cache exceeded lag budget (stale)",
}


def blend_scores(rule_score: float, ml_score: float | None) -> float:
    strategy = settings.score_blend_strategy
    if ml_score is None or strategy == "rules_only":
        return max(0.0, min(100.0, rule_score))
    if strategy == "max":
        return max(0.0, min(100.0, max(rule_score, ml_score)))
    return max(0.0, min(100.0, (rule_score + ml_score) / 2))


def compute_fallback_reason(
    degrade_tags: list[str], step_trace: list[dict[str, Any]]
) -> str | None:
    """Compact audit field when rules-only or degraded path was used."""
    tag_map = {
        "lists:unavailable": "circuit_list",
        "graph:unavailable": "circuit_graph",
        "enrichment:unavailable": "circuit_feature",
        "ml:unavailable": "circuit_ml",
        "opa:unavailable": "circuit_opa",
        "calibration:unavailable": "circuit_calibration",
        "counter:unavailable": "circuit_counter",
        "location:unavailable": "circuit_location",
        "consortium:unavailable": "circuit_consortium",
        "redis:tenant_flags_unavailable": "circuit_redis_tenant_flags",
        "redis:entity_tags_unavailable": "circuit_redis_entity_tags",
        "redis:tag_merge_unavailable": "circuit_redis_tag_merge",
        "async_osint:unavailable": "async_osint_redis",
        "async_enrich:stale": "async_enrich_stale",
        "counter:fallback_local_agg": "counter_local_aggregate_fallback",
        "lists:disabled_by_tenant": "tenant_disable_entity_lists",
        "graph:disabled_by_tenant": "tenant_disable_graph",
        "enrichment:disabled_by_tenant": "tenant_disable_feature_service",
        "ml:disabled_by_tenant": "tenant_disable_ml",
        "opa:disabled_by_tenant": "tenant_disable_opa",
    }
    parts: list[str] = []
    seen: set[str] = set()
    for t in degrade_tags:
        code = tag_map.get(t)
        if code and code not in seen:
            seen.add(code)
            parts.append(code)
    for tr in step_trace:
        if tr.get("status") == "skipped" and tr.get("reason"):
            key = f"step_{tr.get('step', '?')}:{tr['reason']}"
            if key not in seen:
                seen.add(key)
                parts.append(key)
    if settings.score_blend_strategy == "rules_only" and "rules_only_blend" not in seen:
        parts.append("rules_only_blend")
        seen.add("rules_only_blend")
    return "; ".join(parts) if parts else None


def signal_availability_notes_from_tags(degrade_tags: list[str]) -> list[str]:
    """Human-readable audit lines when external signal paths tripped or fell back."""
    out: list[str] = []
    seen: set[str] = set()
    for t in degrade_tags:
        msg = _SIGNAL_UNAVAILABLE_AUDIT.get(t)
        if msg and msg not in seen:
            seen.add(msg)
            out.append(msg)
    return out


def decision_runtime_status(degrade_tags: list[str], notes: list[str]) -> str:
    if notes:
        return "Degraded"
    if "load_shedding:active" in degrade_tags:
        return "Degraded"
    if "counter:fallback_local_agg" in degrade_tags:
        return "Degraded"
    return "Healthy"
