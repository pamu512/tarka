"""Fail-soft HTTP client for the decision context graph (graph-service).

Never raises to callers. Controlled by DECISION_GRAPH_ENABLED + GRAPH_SERVICE_URL
(or DECISION_GRAPH_URL). Timeout defaults to 2s.
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger("tarka.decision_graph")


def graph_write_url_configured() -> bool:
    return bool(_base_url())


def _enabled() -> bool:
    raw = (os.environ.get("DECISION_GRAPH_ENABLED") or "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    return bool(_base_url())


def _base_url() -> str:
    for key in ("DECISION_GRAPH_URL", "GRAPH_SERVICE_URL"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v.rstrip("/")
    return ""


def _timeout() -> float:
    try:
        return max(0.2, min(float(os.environ.get("DECISION_GRAPH_TIMEOUT_SECONDS") or "2"), 10.0))
    except ValueError:
        return 2.0


def _headers() -> dict[str, str]:
    key = (os.environ.get("GRAPH_SERVICE_API_KEY") or os.environ.get("API_KEY") or "").strip()
    h = {"Content-Type": "application/json"}
    if key:
        h["X-API-Key"] = key
    return h


def _request(
    method: str, path: str, *, params: dict[str, Any] | None = None, json_body: dict | None = None
) -> Any:
    if not _enabled():
        return None
    base = _base_url()
    if not base:
        return None
    try:
        import httpx
    except ImportError:
        return None
    try:
        with httpx.Client(timeout=_timeout()) as client:
            r = client.request(
                method,
                f"{base}{path}",
                params={k: v for k, v in (params or {}).items() if v is not None},
                json=json_body,
                headers=_headers(),
            )
            if r.status_code >= 400:
                return None
            return r.json()
    except Exception:
        log.warning("decision_graph_request_fail path=%s", path, exc_info=True)
        return None


def record_decision_failsoft(payload: dict[str, Any]) -> str | None:
    """POST /v1/decisions. Returns external_id or None on any failure / disabled."""
    data = _request("POST", "/v1/decisions", json_body=payload)
    if not isinstance(data, dict):
        log.warning("decision_graph_write_fail")
        return None
    return str(data.get("external_id") or "") or None


def find_latest_failsoft(
    tenant_id: str,
    *,
    kind: str | None = None,
    trace_id: str | None = None,
    case_id: str | None = None,
    entity_external_id: str | None = None,
    agent_run_id: str | None = None,
) -> dict[str, Any] | None:
    data = _request(
        "GET",
        "/v1/decisions/latest",
        params={
            "tenant_id": tenant_id,
            "kind": kind,
            "trace_id": trace_id,
            "case_id": case_id,
            "entity_external_id": entity_external_id,
            "agent_run_id": agent_run_id,
        },
    )
    return data if isinstance(data, dict) else None


def search_decisions_failsoft(
    tenant_id: str,
    *,
    case_id: str | None = None,
    trace_id: str | None = None,
    entity_external_id: str | None = None,
    kind: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    data = _request(
        "GET",
        "/v1/decisions/search",
        params={
            "tenant_id": tenant_id,
            "case_id": case_id,
            "trace_id": trace_id,
            "entity_external_id": entity_external_id,
            "kind": kind,
            "limit": limit,
        },
    )
    if isinstance(data, dict):
        items = data.get("decisions")
        return list(items) if isinstance(items, list) else []
    return []


def resolve_prior_evaluate_id(tenant_id: str, trace_id: str | None) -> str | None:
    tid = (trace_id or "").strip()
    if not tid:
        return None
    row = find_latest_failsoft(tenant_id, kind="evaluate", trace_id=tid)
    return str(row.get("external_id") or "") if row else None


def resolve_disposition_to_supersede(tenant_id: str, case_id: str) -> str:
    """Latest human_disposition on the case (to invalidate + SUPERSEDES on correction)."""
    cid = (case_id or "").strip()
    if not cid:
        return ""
    row = find_latest_failsoft(tenant_id, kind="human_disposition", case_id=cid)
    return str(row.get("external_id") or "") if row else ""


def resolve_prior_agent_advise_id(tenant_id: str, case_id: str | None) -> str | None:
    cid = (case_id or "").strip()
    if not cid:
        return None
    row = find_latest_failsoft(tenant_id, kind="agent_advise", case_id=cid)
    return str(row.get("external_id") or "") if row else None


def get_chain_failsoft(
    tenant_id: str, external_id: str, max_depth: int = 5
) -> dict[str, Any] | None:
    data = _request(
        "GET",
        f"/v1/decisions/{external_id}/chain",
        params={"tenant_id": tenant_id, "max_depth": max_depth},
    )
    return data if isinstance(data, dict) else None


def invalidate_decision_failsoft(
    tenant_id: str,
    external_id: str,
    *,
    reason: str = "",
    supersede_to: str | None = None,
) -> dict[str, Any] | None:
    """POST /v1/decisions/{id}/invalidate. Fail-soft; never raises."""
    did = (external_id or "").strip()
    if not did:
        return None
    data = _request(
        "POST",
        f"/v1/decisions/{did}/invalidate",
        json_body={
            "tenant_id": tenant_id,
            "reason": reason or "",
            "supersede_to": (supersede_to or "").strip() or None,
        },
    )
    return data if isinstance(data, dict) else None


def find_precedents_failsoft(
    tenant_id: str,
    *,
    from_external_id: str | None = None,
    category: str | None = None,
    outcome: str | None = None,
    kind: str | None = None,
    entity_external_id: str | None = None,
    rule_ids: list[str] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    data = _request(
        "GET",
        "/v1/decisions/precedents",
        params={
            "tenant_id": tenant_id,
            "from_external_id": from_external_id,
            "category": category,
            "outcome": outcome,
            "kind": kind,
            "entity_external_id": entity_external_id,
            "rule_ids": ",".join(rule_ids) if rule_ids else None,
            "limit": limit,
        },
    )
    if isinstance(data, dict):
        items = data.get("decisions")
        return list(items) if isinstance(items, list) else []
    return []


def get_impact_failsoft(
    tenant_id: str, external_id: str, max_depth: int = 5
) -> dict[str, Any] | None:
    data = _request(
        "GET",
        f"/v1/decisions/{external_id}/impact",
        params={"tenant_id": tenant_id, "max_depth": max_depth},
    )
    return data if isinstance(data, dict) else None
