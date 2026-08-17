"""HTTP handlers for decision context graph."""

from __future__ import annotations

import os
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from . import decision_context_store as store
from .decision_graph_mirror import schedule_mirror

router = APIRouter(tags=["decision-context"])

DecisionKind = Literal["evaluate", "agent_advise", "human_disposition", "policy_gate"]


def decision_graph_enabled() -> bool:
    raw = (os.environ.get("DECISION_GRAPH_ENABLED") or "1").strip().lower()
    return raw in {"1", "true", "yes", "on"}


class DecisionEdgeIn(BaseModel):
    from_external_id: str
    relationship: str = Field(description="CAUSED | INFLUENCED | PRECEDENT_FOR | SUPERSEDES")


class RecordDecisionRequest(BaseModel):
    tenant_id: str
    kind: DecisionKind
    category: str
    scenario: str
    outcome: str
    reasoning: str = ""
    confidence: float | None = None
    rule_ids: list[str] = Field(default_factory=list)
    audit_log_id: str | None = None
    agent_run_id: str | None = None
    case_id: str | None = None
    trace_id: str | None = None
    entity_external_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    shadow: bool = False
    external_id: str | None = None
    semantica_decision_id: str | None = None
    edges: list[DecisionEdgeIn] = Field(
        default_factory=list,
        description="Causal edges FROM listed parents TO this decision",
    )


class InvalidateRequest(BaseModel):
    tenant_id: str
    reason: str = ""
    supersede_to: str | None = Field(
        default=None,
        description="Replacement decision external_id (SUPERSEDES edge)",
    )


def _require_enabled() -> None:
    if not decision_graph_enabled():
        raise HTTPException(status_code=503, detail="decision_graph_disabled")


def _maybe_mirror_semantica(body: RecordDecisionRequest, did: str, row: dict[str, Any]) -> dict[str, Any]:
    if (os.environ.get("SEMANTICA_BRIDGE_ENABLED") or "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return row
    try:
        import sys
        from pathlib import Path

        bridge_root = Path(__file__).resolve().parents[3] / "semantica-bridge"
        if str(bridge_root) not in sys.path:
            sys.path.insert(0, str(bridge_root))
        from semantica_bridge import mirror_decision

        parent_sem = None
        for edge in body.edges:
            parent = store.get_decision(body.tenant_id, edge.from_external_id)
            if parent and parent.get("semantica_decision_id"):
                parent_sem = parent["semantica_decision_id"]
                break
        mirrored = mirror_decision(
            category=body.category,
            scenario=body.scenario,
            reasoning=body.reasoning,
            outcome=body.outcome,
            confidence=body.confidence,
            parent_semantica_id=parent_sem,
            relationship=(body.edges[0].relationship if body.edges else "INFLUENCED"),
        )
        if mirrored.ok and mirrored.semantica_decision_id:
            store.set_semantica_decision_id(
                body.tenant_id, did, mirrored.semantica_decision_id
            )
            return store.get_decision(body.tenant_id, did) or row
    except Exception:
        pass
    return row


@router.post("/v1/decisions")
def post_decision(body: RecordDecisionRequest) -> dict[str, Any]:
    _require_enabled()
    try:
        did = store.record_decision(
            tenant_id=body.tenant_id,
            kind=body.kind,
            category=body.category,
            scenario=body.scenario,
            outcome=body.outcome,
            reasoning=body.reasoning,
            confidence=body.confidence,
            rule_ids=body.rule_ids,
            audit_log_id=body.audit_log_id,
            agent_run_id=body.agent_run_id,
            case_id=body.case_id,
            trace_id=body.trace_id,
            entity_external_ids=body.entity_external_ids,
            evidence_ids=body.evidence_ids,
            shadow=body.shadow,
            external_id=body.external_id,
            semantica_decision_id=body.semantica_decision_id,
        )
        for edge in body.edges:
            store.add_edge(
                body.tenant_id,
                edge.from_external_id,
                did,
                edge.relationship,
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    row = store.get_decision(body.tenant_id, did)
    assert row is not None
    row = _maybe_mirror_semantica(body, did, row)
    schedule_mirror(body.tenant_id, row)
    return row


@router.get("/v1/decisions/latest")
def get_latest_decision(
    tenant_id: str,
    kind: str | None = None,
    trace_id: str | None = None,
    case_id: str | None = None,
    entity_external_id: str | None = None,
    agent_run_id: str | None = None,
) -> dict[str, Any]:
    _require_enabled()
    row = store.find_latest(
        tenant_id,
        kind=kind,
        trace_id=trace_id,
        case_id=case_id,
        entity_external_id=entity_external_id,
        agent_run_id=agent_run_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="decision_not_found")
    return row


@router.get("/v1/decisions/search")
def search_decisions(
    tenant_id: str,
    entity_external_id: str | None = None,
    category: str | None = None,
    outcome: str | None = None,
    kind: str | None = None,
    trace_id: str | None = None,
    case_id: str | None = None,
    agent_run_id: str | None = None,
    q: str | None = None,
    since: str | None = None,
    until: str | None = None,
    include_invalidated: bool = True,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    _require_enabled()
    hits = store.search_decisions(
        tenant_id=tenant_id,
        entity_external_id=entity_external_id,
        category=category,
        outcome=outcome,
        kind=kind,
        trace_id=trace_id,
        case_id=case_id,
        agent_run_id=agent_run_id,
        q=q,
        since=since,
        until=until,
        include_invalidated=include_invalidated,
        limit=limit,
    )
    return {"decisions": hits}


@router.get("/v1/decisions/{external_id}")
def get_decision(
    external_id: str,
    tenant_id: str,
    include_neighbors: bool = Query(default=False),
) -> dict[str, Any]:
    _require_enabled()
    row = store.get_decision(tenant_id, external_id)
    if row is None:
        raise HTTPException(status_code=404, detail="decision_not_found")
    if include_neighbors:
        row = {
            **row,
            "neighbors": store.get_neighbor_summary(tenant_id, external_id),
        }
    return row


@router.get("/v1/decisions/{external_id}/chain")
def get_chain(
    external_id: str,
    tenant_id: str,
    max_depth: int = Query(default=5, ge=1, le=20),
) -> dict[str, Any]:
    _require_enabled()
    if store.get_decision(tenant_id, external_id) is None:
        raise HTTPException(status_code=404, detail="decision_not_found")
    return store.get_chain(tenant_id, external_id, max_depth=max_depth)


@router.get("/v1/decisions/{external_id}/impact")
def get_impact(
    external_id: str,
    tenant_id: str,
    max_depth: int = Query(default=5, ge=1, le=20),
) -> dict[str, Any]:
    _require_enabled()
    if store.get_decision(tenant_id, external_id) is None:
        raise HTTPException(status_code=404, detail="decision_not_found")
    return store.get_impact(tenant_id, external_id, max_depth=max_depth)


@router.post("/v1/decisions/{external_id}/invalidate")
def invalidate(external_id: str, body: InvalidateRequest) -> dict[str, Any]:
    _require_enabled()
    row = store.invalidate_decision(
        body.tenant_id,
        external_id,
        body.reason,
        supersede_to=body.supersede_to,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="decision_not_found")
    return row
