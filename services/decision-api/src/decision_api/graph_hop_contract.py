"""Evaluate-side graph hop contract v1.2 — role check + pack-why answers."""

from __future__ import annotations

from typing import Any

from graph_contract import require_role
from graph_pack_atoms import hop_view_from_graph_meta, pack_why_from_hop


def validate_evaluate_roles(
    tenant_id: str,
    role: str | None,
    parties: list[Any] | None = None,
) -> str:
    primary = require_role(tenant_id, role or "")
    for raw in parties or []:
        if isinstance(raw, dict):
            require_role(tenant_id, str(raw.get("role") or ""))
        else:
            party_role = getattr(raw, "role", None)
            require_role(tenant_id, str(party_role or ""))
    return primary


def graph_pack_why(
    graph_meta: dict[str, Any] | None,
    *,
    graph_url: str = "",
    degrade_tags: list[str] | None = None,
    tenant_id: str = "",
    subject_id: str = "",
) -> dict[str, Any]:
    hop = hop_view_from_graph_meta(
        graph_meta,
        graph_url=graph_url,
        degrade_tags=degrade_tags,
        tenant_id=tenant_id,
        subject_id=subject_id,
    )
    return {"graph": pack_why_from_hop(hop)}
