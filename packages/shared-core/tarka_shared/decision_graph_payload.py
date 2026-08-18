"""Shared payload builders for the decision context graph (all writers use this)."""

from __future__ import annotations

from typing import Any


def resolve_prior_evaluate_id(tenant_id: str, trace_id: str | None, metadata: dict | None) -> str:
    prior = ""
    if isinstance(metadata, dict):
        prior = str(metadata.get("prior_decision_id") or "").strip()
    if prior:
        return prior
    try:
        from tarka_shared.decision_graph_client import resolve_prior_evaluate_id as _resolve

        return _resolve(tenant_id, trace_id) or ""
    except ImportError:
        return ""


def resolve_prior_agent_advise_id(
    tenant_id: str, case_id: str | None, metadata: dict | None
) -> str:
    prior = ""
    if isinstance(metadata, dict):
        prior = str(metadata.get("prior_decision_id") or "").strip()
    if prior:
        return prior
    try:
        from tarka_shared.decision_graph_client import resolve_prior_agent_advise_id as _resolve

        return _resolve(tenant_id, case_id) or ""
    except ImportError:
        return ""


def resolve_prior_for_disposition(
    tenant_id: str,
    case_id: str,
    trace_id: str | None,
    *,
    agent_run_id: str | None = None,
    explicit_prior: str | None = None,
) -> str:
    prior = (explicit_prior or "").strip()
    if prior:
        return prior
    try:
        from tarka_shared.decision_graph_client import (
            find_latest_failsoft,
            resolve_prior_agent_advise_id,
            resolve_prior_evaluate_id,
        )
    except ImportError:
        return ""
    if agent_run_id:
        row = find_latest_failsoft(tenant_id, agent_run_id=agent_run_id, kind="agent_advise")
        if row:
            return str(row.get("external_id") or "")
    prior = resolve_prior_agent_advise_id(tenant_id, case_id) or ""
    if not prior and trace_id:
        prior = resolve_prior_evaluate_id(tenant_id, trace_id) or ""
    return prior


def build_evaluate_payload(
    *,
    tenant_id: str,
    trace_id: str,
    entity_id: str,
    event_type: str,
    decision: str,
    score: float,
    rule_hits: list[str] | None,
    fallback_reason: str | None,
    payload: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
    decision_log_record: dict[str, Any] | None,
    shadow_request: bool,
) -> dict[str, Any]:
    prior = resolve_prior_evaluate_id(tenant_id, trace_id, metadata)
    edges: list[dict[str, str]] = []
    if prior:
        edges.append({"from_external_id": prior, "relationship": "INFLUENCED"})
    reasoning_parts: list[str] = []
    if rule_hits:
        reasoning_parts.append("rules=" + ",".join(rule_hits[:12]))
    if fallback_reason:
        reasoning_parts.append(f"fallback={fallback_reason}")
    entity_ids = [entity_id] if entity_id else []
    pl = payload if isinstance(payload, dict) else {}
    for key in ("device_id", "account_id", "payment_id", "user_id"):
        val = pl.get(key)
        if val and str(val) not in entity_ids:
            entity_ids.append(str(val))
    audit_log_id = None
    if isinstance(decision_log_record, dict):
        audit_log_id = (
            str(
                decision_log_record.get("audit_log_id") or decision_log_record.get("id") or ""
            ).strip()
            or None
        )
    evidence_ids: list[str] = []
    return {
        "tenant_id": tenant_id,
        "kind": "evaluate",
        "category": "transaction_evaluate",
        "scenario": f"{event_type}:{entity_id}",
        "outcome": str(decision),
        "reasoning": "; ".join(reasoning_parts) or "evaluate",
        "confidence": float(score) if score is not None else None,
        "rule_ids": list(rule_hits or [])[:32],
        "entity_external_ids": entity_ids[:32],
        "trace_id": trace_id,
        "audit_log_id": audit_log_id,
        "evidence_ids": evidence_ids,
        "shadow": bool(shadow_request),
        "edges": edges,
    }


def build_agent_advise_payload(
    *,
    tenant_id: str,
    run_id: str,
    case_id: str | None,
    entity_ids: list[str] | None,
    trace_ids: list[str] | None,
    claims: list[dict[str, Any]] | None,
    context_snapshot: dict[str, Any] | None,
    source: str,
) -> dict[str, Any]:
    prior = ""
    if isinstance(context_snapshot, dict):
        prior = str(context_snapshot.get("prior_decision_id") or "").strip()
    if not prior and trace_ids:
        prior = resolve_prior_evaluate_id(tenant_id, str(trace_ids[0]), context_snapshot)
    edges: list[dict[str, str]] = []
    if prior:
        edges.append({"from_external_id": prior, "relationship": "INFLUENCED"})
    evidence: list[str] = []
    for claim in claims or []:
        if not isinstance(claim, dict):
            continue
        for eid in claim.get("evidence_ids") or []:
            s = str(eid).strip()
            if s and s not in evidence:
                evidence.append(s)
    outcome = "advise"
    if claims:
        outcome = str((claims[0] or {}).get("claim") or (claims[0] or {}).get("text") or "advise")[
            :128
        ]
    return {
        "tenant_id": (tenant_id or "").strip(),
        "kind": "agent_advise",
        "category": f"agent_run:{source}",
        "scenario": f"agent_run case={case_id or '-'}",
        "outcome": outcome or "advise",
        "reasoning": f"agent_run_id={run_id}; claims={len(claims or [])}",
        "agent_run_id": run_id,
        "case_id": case_id,
        "trace_id": (trace_ids or [None])[0],
        "entity_external_ids": list(entity_ids or [])[:32],
        "evidence_ids": evidence[:64],
        "edges": edges,
    }


def build_human_disposition_payload(
    *,
    tenant_id: str,
    case_id: str,
    entity_id: str | None,
    trace_id: str | None,
    status: str,
    actor_id: str,
    reason_code: str | None,
    prior_decision_id: str | None = None,
    agent_run_id: str | None = None,
) -> dict[str, Any]:
    prior = resolve_prior_for_disposition(
        tenant_id,
        case_id,
        trace_id,
        agent_run_id=agent_run_id,
        explicit_prior=prior_decision_id,
    )
    edges: list[dict[str, str]] = []
    if prior:
        edges.append({"from_external_id": prior, "relationship": "CAUSED"})
    return {
        "tenant_id": tenant_id,
        "kind": "human_disposition",
        "category": "case_status",
        "scenario": f"case {case_id} → {status}",
        "outcome": str(status),
        "reasoning": f"actor={actor_id}" + (f"; reason={reason_code}" if reason_code else ""),
        "case_id": case_id,
        "entity_external_ids": [entity_id] if entity_id else [],
        "trace_id": trace_id,
        "edges": edges,
    }
