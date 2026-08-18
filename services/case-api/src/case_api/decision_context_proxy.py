"""Proxy helpers for graph-service decision context API."""

from __future__ import annotations

import os
from typing import Any

import httpx

from .config import settings


def _headers() -> dict[str, str]:
    key = (os.environ.get("GRAPH_SERVICE_API_KEY") or os.environ.get("API_KEY") or "").strip()
    h: dict[str, str] = {}
    if key:
        h["X-API-Key"] = key
    return h


async def fetch_decisions_for_case(
    http: httpx.AsyncClient,
    *,
    tenant_id: str,
    case_id: str,
    trace_id: str | None,
    limit: int = 50,
) -> dict[str, Any]:
    base = (settings.graph_service_url or "").strip().rstrip("/")
    if not base:
        return {"decisions": [], "message": "GRAPH_SERVICE_URL not set"}
    headers = _headers()
    try:
        by_case = await http.get(
            f"{base}/v1/decisions/search",
            params={"tenant_id": tenant_id, "case_id": case_id, "limit": limit},
            headers=headers,
            timeout=5.0,
        )
        by_case.raise_for_status()
        decisions = list((by_case.json() or {}).get("decisions") or [])
        if trace_id and len(decisions) < limit:
            by_trace = await http.get(
                f"{base}/v1/decisions/search",
                params={"tenant_id": tenant_id, "trace_id": trace_id, "limit": limit},
                headers=headers,
                timeout=5.0,
            )
            by_trace.raise_for_status()
            seen = {d.get("external_id") for d in decisions}
            for row in (by_trace.json() or {}).get("decisions") or []:
                eid = row.get("external_id")
                if eid and eid not in seen:
                    decisions.append(row)
                    seen.add(eid)
        decisions.sort(key=lambda d: str(d.get("created_at") or ""), reverse=True)
        return {"decisions": decisions[:limit], "case_id": case_id}
    except httpx.HTTPStatusError as exc:
        return {"decisions": [], "message": f"graph_service_http_{exc.response.status_code}"}
    except Exception:
        return {"decisions": [], "message": "graph_service_unreachable"}


async def fetch_decision_chain(
    http: httpx.AsyncClient,
    *,
    tenant_id: str,
    external_id: str,
    max_depth: int = 5,
) -> dict[str, Any]:
    base = (settings.graph_service_url or "").strip().rstrip("/")
    if not base:
        return {"nodes": [], "edges": [], "message": "GRAPH_SERVICE_URL not set"}
    try:
        r = await http.get(
            f"{base}/v1/decisions/{external_id}/chain",
            params={"tenant_id": tenant_id, "max_depth": max_depth},
            headers=_headers(),
            timeout=5.0,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return {"nodes": [], "edges": [], "message": "graph_service_unreachable"}


async def fetch_accountability_snapshot(
    http: httpx.AsyncClient,
    *,
    tenant_id: str,
    case_id: str,
    trace_id: str | None,
    limit: int = 50,
) -> dict[str, Any]:
    """Bundle-ready snapshot: decisions + causal edges within the case/trace scope."""
    block = await fetch_decisions_for_case(
        http,
        tenant_id=tenant_id,
        case_id=case_id,
        trace_id=trace_id,
        limit=limit,
    )
    decisions = block.get("decisions") or []
    if not decisions:
        return {
            "schema_id": "tarka.decision_context/v1",
            "decisions": [],
            "edges": [],
            "message": block.get("message"),
        }
    ids = {d.get("external_id") for d in decisions if d.get("external_id")}
    edges: list[dict[str, str]] = []
    base = (settings.graph_service_url or "").strip().rstrip("/")
    if base:
        for d in decisions:
            did = str(d.get("external_id") or "")
            if not did:
                continue
            try:
                r = await http.get(
                    f"{base}/v1/decisions/{did}",
                    params={"tenant_id": tenant_id, "include_neighbors": "true"},
                    headers=_headers(),
                    timeout=3.0,
                )
                if r.status_code != 200:
                    continue
                neighbors = (r.json() or {}).get("neighbors") or {}
                for inbound in neighbors.get("inbound") or []:
                    frm = inbound.get("from_external_id")
                    if frm in ids:
                        edges.append(
                            {
                                "from_external_id": frm,
                                "to_external_id": did,
                                "relationship": inbound.get("relationship"),
                            }
                        )
            except Exception:
                continue
    return {
        "schema_id": "tarka.decision_context/v1",
        "decisions": decisions,
        "edges": edges,
    }
