"""Persisted entity resolution on top of the existing shared-attribute analytics.

Candidate generation reuses ``algorithms_age.find_shared_attributes``; each
confirmed merge becomes a mutual ``ALIAS_OF`` edge written through
``graph_runtime.create_link`` so the tenant schema, sanitizers, and the F1
provenance envelope apply uniformly. Resolution metadata rides the edge
(``resolution_strategy``, ``resolution_attribute``, ``resolution_value``),
making every merge explainable after the fact.
"""

from __future__ import annotations

from typing import Any

from .algorithms_age import find_shared_attributes
from .entity_risk_score import link_props_for_create


def _pair_key(from_id: str, to_id: str) -> tuple[str, str]:
    return tuple(sorted((from_id, to_id)))  # type: ignore[return-value]


async def resolve_entity_candidates(
    tenant_id: str,
    attribute: str = "device_id",
    min_shared: int = 2,
) -> dict[str, Any]:
    """Turn shared-attribute groups into deduplicated candidate pairs."""
    groups = await find_shared_attributes(tenant_id, attribute, min_shared)
    seen: set[tuple[str, str]] = set()
    candidates: list[dict[str, Any]] = []
    for group in groups:
        ids = [str(e) for e in group.get("entity_ids") or []]
        for i, a in enumerate(ids):
            for b in ids[i + 1 :]:
                key = _pair_key(a, b)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(
                    {
                        "from_id": a,
                        "to_id": b,
                        "attribute": group.get("attribute"),
                        "shared_value": group.get("shared_value"),
                        "group_size": group.get("group_size"),
                        "strategy": "shared_attribute",
                    }
                )
    return {"tenant_id": tenant_id, "attribute": attribute, "candidates": candidates}


async def resolve_entities(
    tenant_id: str,
    candidates: list[dict[str, Any]],
    *,
    create_link: Any | None = None,
) -> dict[str, Any]:
    """Persist confirmed merges as mutual ``ALIAS_OF`` edges with provenance."""
    if create_link is None:
        from .graph_runtime import create_link as create_link_impl

        create_link = create_link_impl

    written: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for candidate in candidates or []:
        from_id = str(candidate.get("from_id") or "").strip()
        to_id = str(candidate.get("to_id") or "").strip()
        if not from_id or not to_id:
            raise ValueError("resolution candidate requires from_id and to_id")
        if from_id == to_id:
            raise ValueError(f"self-loop resolution rejected: {from_id!r}")
        key = _pair_key(from_id, to_id)
        if key in seen_pairs:
            continue
        seen_pairs.add(key)

        props = link_props_for_create(
            {
                "resolution_strategy": str(candidate.get("strategy") or "shared_attribute"),
                "resolution_attribute": str(candidate.get("attribute") or ""),
                "resolution_value": str(candidate.get("shared_value") or ""),
            }
        )
        await create_link(tenant_id, from_id, to_id, "ALIAS_OF", props)
        written.append({"from_id": from_id, "to_id": to_id, "properties": props})

    return {"tenant_id": tenant_id, "merged": len(written), "edges": written}
