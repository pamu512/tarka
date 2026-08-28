"""Evaluate-side graph hop contract v1.2 — role check + pack-why answers."""

from __future__ import annotations

from typing import Any

from graph_contract import (
    consume_graph_answers,
    pack_why_from_graph_answers,
    require_role,
)


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


def graph_pack_why(graph_meta: dict[str, Any] | None) -> dict[str, Any]:
    return {"graph": pack_why_from_graph_answers(consume_graph_answers(graph_meta))}
