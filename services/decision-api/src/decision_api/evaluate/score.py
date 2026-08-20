"""Score / fallback helpers for the evaluate pipeline."""

from __future__ import annotations

from typing import Any

from decision_api.config import settings

_SIGNAL_UNAVAILABLE_AUDIT: dict[str, str] = {
    "lists:unavailable": "Signal Entity lists was unavailable",
    "graph:unavailable": "Signal Graph risk was unavailable",
    "graph:unconfigured": "Signal Graph risk URL unset",
    "enrichment:unavailable": "Signal Feature enrichment was unavailable",
    "enrichment:unconfigured": "Signal Feature enrichment URL unset",
    "ml:unavailable": "Signal ML scoring was unavailable",
    "ml:unconfigured": "Signal ML scoring URL unset",
    "ml:disabled": "Signal ML scoring disabled",
    "opa:unavailable": "Signal Policy (OPA) was unavailable",
    "opa:unconfigured": "Signal Policy (OPA) URL unset",
    "calibration:unavailable": "Signal Calibration was unavailable",
    "calibration:unconfigured": "Signal Calibration URL unset",
    "counter:unavailable": "Signal Counter service was unavailable",
    "counter:unconfigured": "Signal Counter service URL unset",
    "location:unavailable": "Signal Location intelligence was unavailable",
    "location:unconfigured": "Signal Location intelligence URL unset",
    "redis:tag_merge_unavailable": "Signal Redis tag merge was unavailable",
    "redis:tenant_flags_unavailable": "Signal Redis tenant flags was unavailable",
    "redis:entity_tags_unavailable": "Signal Redis entity tags was unavailable",
    "consortium:unavailable": "Signal Consortium cross-tenant signal was unavailable",
    "async_osint:unavailable": "Signal Async OSINT cache was unavailable",
    "async_enrich:stale": "Async OSINT cache exceeded lag budget (stale)",
}


EVALUATE_HOP_UNCONFIGURED: dict[str, tuple[str, str]] = {
    "graph": ("graph_service_url", "graph:unconfigured"),
    "features": ("feature_service_url", "enrichment:unconfigured"),
    "ml": ("ml_scoring_url", "ml:unconfigured"),
    "opa": ("opa_url", "opa:unconfigured"),
    "counter": ("counter_service_url", "counter:unconfigured"),
    "location": ("location_service_url", "location:unconfigured"),
    "calibration": ("calibration_service_url", "calibration:unconfigured"),
}


def tag_unconfigured(degrade_tags: list[str], url: str, tag: str) -> bool:
    """Tag an empty hop URL. Returns True when the hop should be skipped."""
    if (url or "").strip():
        return False
    if tag not in degrade_tags:
        degrade_tags.append(tag)
    return True


def tag_hop_unconfigured(
    degrade_tags: list[str], hop: str, url: str | None = None
) -> bool:
    attr, tag = EVALUATE_HOP_UNCONFIGURED[hop]
    resolved = getattr(settings, attr) if url is None else url
    return tag_unconfigured(degrade_tags, resolved, tag)


def optional_score(data: dict[str, Any] | None, key: str = "score") -> float | None:
    """Missing / null score is unscored. ``0`` is a real score when the key is present."""
    if not isinstance(data, dict) or key not in data or data[key] is None:
        return None
    try:
        return float(data[key])
    except (TypeError, ValueError):
        return None


def parse_ml_score_payload(
    data: dict[str, Any] | None,
) -> tuple[float | None, dict[str, Any]]:
    """Treat disabled / missing score as unscored. ``0`` is a real score when present."""
    if not isinstance(data, dict):
        return None, {"unscored_reason": "missing_score"}
    if data.get("scored") is False or data.get("model_version") == "disabled":
        return None, {"unscored_reason": "disabled"}
    score = optional_score(data)
    if score is None:
        return None, {"unscored_reason": "missing_score"}
    factors = data.get("ml_top_factors")
    if not isinstance(factors, list):
        factors = []
    summary = data.get("ml_summary")
    if summary is not None and not isinstance(summary, str):
        summary = str(summary)[:500]
    model = data.get("model")
    return score, {
        "top_factors": factors,
        "summary": summary,
        "model": model if isinstance(model, str) else None,
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
        "graph:unconfigured": "graph_unconfigured",
        "enrichment:unavailable": "circuit_feature",
        "enrichment:unconfigured": "feature_unconfigured",
        "ml:unavailable": "circuit_ml",
        "ml:unconfigured": "ml_unconfigured",
        "ml:disabled": "ml_disabled",
        "opa:unavailable": "circuit_opa",
        "opa:unconfigured": "opa_unconfigured",
        "calibration:unavailable": "circuit_calibration",
        "calibration:unconfigured": "calibration_unconfigured",
        "counter:unconfigured": "counter_unconfigured",
        "location:unconfigured": "location_unconfigured",
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


_DEGRADE_SKIP_SCORE: dict[str, float] = {
    "lists:unavailable": 5.0,
    "graph:unavailable": 5.0,
    "graph:unconfigured": 5.0,
    "graph:stale_skipped": 5.0,
    "enrichment:unavailable": 5.0,
    "enrichment:unconfigured": 5.0,
    "ml:unavailable": 5.0,
    "ml:unconfigured": 5.0,
    "ml:disabled": 5.0,
    "opa:unavailable": 5.0,
    "opa:unconfigured": 5.0,
    "calibration:unavailable": 5.0,
    "calibration:unconfigured": 5.0,
    "counter:unavailable": 5.0,
    "counter:unconfigured": 5.0,
    "location:unavailable": 5.0,
    "location:unconfigured": 5.0,
    "redis:tag_merge_unavailable": 5.0,
    "redis:tenant_flags_unavailable": 5.0,
    "redis:entity_tags_unavailable": 5.0,
}


def degrade_skip_score_delta(degrade_tags: list[str]) -> float:
    """Modest score bump (+5 each) for skipped/unavailable first-party hops.

    Makes the entity warmer ("showing signs") when checks are missing,
    without forcing deny unless the explicit fail-closed opt-in is on.
    """
    # ponytail: flat 5 per tag; upgrade to per-hop weights if product needs tiering.
    total = 0.0
    for tag in degrade_tags:
        total += _DEGRADE_SKIP_SCORE.get(tag, 0.0)
    return total


def decision_runtime_status(degrade_tags: list[str], notes: list[str]) -> str:
    if notes:
        return "Degraded"
    if "load_shedding:active" in degrade_tags:
        return "Degraded"
    if "counter:fallback_local_agg" in degrade_tags:
        return "Degraded"
    return "Healthy"
