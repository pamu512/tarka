"""Heterogeneous graph edge validation (xFraud-style typed endpoints).

When a tenant schema defines ``typed_edges``, ``create_link`` enforces that the
Neo4j/Janus endpoints carry at least one label matching the allowed from/to sets.
"""

from __future__ import annotations

from typing import Any, Sequence

from graph_service.custom_schema import load_tenant_schema


def _norm_rel(rel: str) -> str:
    return str(rel or "").upper().replace(" ", "_").replace("-", "_")


def typed_edge_specs(tenant_id: str) -> list[dict[str, Any]]:
    return list(load_tenant_schema(tenant_id).typed_edges or [])


def validate_typed_edge_or_raise(
    tenant_id: str,
    relationship: str,
    from_labels: Sequence[str],
    to_labels: Sequence[str],
) -> None:
    """Raise ValueError if relationship is constrained and endpoint labels violate all OR alternatives."""
    rel = _norm_rel(relationship)
    specs = [s for s in typed_edge_specs(tenant_id) if _norm_rel(str(s.get("relationship", ""))) == rel]
    if not specs:
        return
    from_set = {str(x) for x in from_labels if str(x).strip()}
    to_set = {str(x) for x in to_labels if str(x).strip()}
    for spec in specs:
        ft = {str(x).strip() for x in (spec.get("from_entity_types") or []) if str(x).strip()}
        tt = {str(x).strip() for x in (spec.get("to_entity_types") or []) if str(x).strip()}
        if not ft or not tt:
            continue
        if (from_set & ft) and (to_set & tt):
            return
    raise ValueError(f"typed edge {rel} not satisfied for endpoint labels {sorted(from_set)} -> {sorted(to_set)} (tenant hetero schema)")
