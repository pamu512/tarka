from __future__ import annotations

from typing import Any

"""Primary relatedness evidence builder for evaluate audit snapshots."""

RELATEDNESS_SCHEMA_ID = "tarka.relatedness_evidence/v1"

# Known co-presence tags only — broad location:/graph: prefixes catch degrade tags
# (e.g. location:unavailable) and would undermine fail-soft emission.
_COHORT_TAG_PREFIXES = (
    "location:copresence_elevated",
    "location:impossible_travel",
    "escalated:copresence",
    "sdk:shared_device",
    "vendor:incognia",
)

_DEVICE_TAG_PREFIXES = ("sdk:shared_device",)


def _cohort_related_tags(tags: list[str] | None) -> list[str]:
    if not tags:
        return []
    out: list[str] = []
    for t in tags:
        s = str(t).strip()
        if not s:
            continue
        if any(s.startswith(p) for p in _COHORT_TAG_PREFIXES):
            out.append(s)
    return out


def _device_related_tags(tags: list[str]) -> list[str]:
    return [t for t in tags if any(t.startswith(p) for p in _DEVICE_TAG_PREFIXES)]


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _graph_seen_at_hints(
    partner_graph_hints: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(partner_graph_hints, dict):
        return [], []
    vertices = partner_graph_hints.get("vertices")
    edges = partner_graph_hints.get("edges")
    places: list[dict[str, Any]] = []
    seen_at: list[dict[str, Any]] = []
    if isinstance(vertices, list):
        for v in vertices:
            if isinstance(v, dict) and v.get("label") == "Place":
                places.append(
                    {
                        "id": str(v.get("id") or "")[:256],
                        "source": (v.get("props") or {}).get("source"),
                    }
                )
    if isinstance(edges, list):
        for e in edges:
            if isinstance(e, dict) and e.get("type") == "SEEN_AT":
                seen_at.append(
                    {
                        "place_id": str((e.get("to") or {}).get("id") or "")[:256],
                        "source": (e.get("props") or {}).get("source"),
                    }
                )
    return places, seen_at


def build_relatedness_evidence(
    *,
    tags: list[str] | None,
    inference_context: dict[str, Any] | None,
    location_meta: dict[str, Any] | None,
    graph_meta: dict[str, Any] | None,
    partner_graph_hints: dict[str, Any] | None = None,
    canary_cohort: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Audit block when relatedness signals exist; None when absent (fail soft)."""
    cohort_tags = _cohort_related_tags(tags)
    inf = inference_context if isinstance(inference_context, dict) else {}
    loc = location_meta if isinstance(location_meta, dict) else {}
    graph = graph_meta if isinstance(graph_meta, dict) else {}

    copresence_risk = _float_or_none(loc.get("copresence_risk"))
    if copresence_risk is None:
        copresence_risk = _float_or_none(inf.get("copresence_risk"))
    impossible_travel = _float_or_none(loc.get("impossible_travel_risk"))
    if impossible_travel is None:
        impossible_travel = _float_or_none(inf.get("impossible_travel_risk"))
    geo_consistency = _float_or_none(loc.get("geo_consistency_risk"))
    if geo_consistency is None:
        geo_consistency = _float_or_none(inf.get("geo_consistency_risk"))
    location_confidence = _float_or_none(loc.get("location_confidence"))
    if location_confidence is None:
        location_confidence = _float_or_none(inf.get("location_confidence"))

    seen_at_peers = _int_or_none(graph.get("seen_at_peer_count_24h"))
    colocated = _int_or_none(graph.get("colocated_entities_24h"))
    place_vertices, seen_at_edges = _graph_seen_at_hints(partner_graph_hints)

    has_signal = (
        (copresence_risk is not None and copresence_risk > 0)
        or (impossible_travel is not None and impossible_travel > 0)
        or (seen_at_peers is not None and seen_at_peers >= 1)
        or (colocated is not None and colocated >= 1)
        or bool(place_vertices)
        or bool(seen_at_edges)
        or bool(cohort_tags)
    )
    if not has_signal:
        return None

    sources: list[str] = []
    if loc:
        sources.append("location_service")
    if graph:
        sources.append("graph")
    if place_vertices or seen_at_edges:
        sources.append("partner_fusion")
    if not sources and inf:
        sources.append("heuristic")

    geo_enrichment: dict[str, Any] = {}
    if copresence_risk is not None:
        geo_enrichment["copresence_risk"] = round(copresence_risk, 4)
    if impossible_travel is not None:
        geo_enrichment["impossible_travel_risk"] = round(impossible_travel, 4)
    if geo_consistency is not None:
        geo_enrichment["geo_consistency_risk"] = round(geo_consistency, 4)
    if location_confidence is not None:
        geo_enrichment["location_confidence"] = round(location_confidence, 4)
    if sources:
        geo_enrichment["sources"] = sources

    graph_block: dict[str, Any] = {}
    if seen_at_peers is not None:
        graph_block["seen_at_peer_count_24h"] = seen_at_peers
    if colocated is not None:
        graph_block["colocated_entities_24h"] = colocated
    if place_vertices:
        graph_block["place_vertices"] = place_vertices
    if seen_at_edges:
        graph_block["seen_at_edges"] = seen_at_edges

    device_block: dict[str, Any] = {}
    device_tags = _device_related_tags(cohort_tags)
    if device_tags:
        device_block["tags"] = device_tags

    out: dict[str, Any] = {
        "schema_id": RELATEDNESS_SCHEMA_ID,
        "graph": graph_block,
        "device": device_block,
    }
    if geo_enrichment:
        out["geo_enrichment"] = geo_enrichment
    if isinstance(canary_cohort, dict) and canary_cohort:
        cohort_subset = {
            k: canary_cohort[k]
            for k in (
                "cohort_sticky_id",
                "cohort_bucket_0_99",
                "salt_version",
                "experiment_id",
            )
            if k in canary_cohort
        }
        if cohort_subset:
            out["cohort"] = cohort_subset
    if cohort_tags:
        out["tags"] = cohort_tags
    return out
