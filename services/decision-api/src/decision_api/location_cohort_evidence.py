from __future__ import annotations

from typing import Any

"""Legacy location cohort evidence alias — delegates to relatedness_evidence."""

from decision_api.relatedness_evidence import build_relatedness_evidence

SCHEMA_ID = "tarka.location_cohort_evidence/v1"


def _legacy_from_relatedness(relatedness: dict[str, Any]) -> dict[str, Any]:
    """Map relatedness_evidence shape to legacy location_cohort_evidence layout."""
    out: dict[str, Any] = {"schema_id": SCHEMA_ID}
    if cohort := relatedness.get("cohort"):
        out["cohort"] = cohort
    if geo := relatedness.get("geo_enrichment"):
        out["copresence"] = geo
    if graph := relatedness.get("graph"):
        out["graph"] = graph
    if tags := relatedness.get("tags"):
        out["tags"] = tags
    return out


def build_location_cohort_evidence(
    *,
    tags: list[str] | None,
    inference_context: dict[str, Any] | None,
    location_meta: dict[str, Any] | None,
    graph_meta: dict[str, Any] | None,
    partner_graph_hints: dict[str, Any] | None,
    canary_cohort: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Legacy alias for build_relatedness_evidence with old schema_id and field layout."""
    relatedness = build_relatedness_evidence(
        tags=tags,
        inference_context=inference_context,
        location_meta=location_meta,
        graph_meta=graph_meta,
        partner_graph_hints=partner_graph_hints,
        canary_cohort=canary_cohort,
    )
    if relatedness is None:
        return None
    return _legacy_from_relatedness(relatedness)
