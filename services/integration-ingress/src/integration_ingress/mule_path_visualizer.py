"""Mule path from TRANSACTED edges already written by evaluate.

Empty graph, missing origin, or an unset GRAPH_SERVICE_URL returns no hops.
This module does not invent people, amounts, or payouts.
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _edge_type(edge: dict[str, Any]) -> str:
    return str(edge.get("type") or edge.get("relationship") or "").strip().upper()


def _end(edge: dict[str, Any], *keys: str) -> str:
    for key in keys:
        raw = edge.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return ""


def _amount(edge: dict[str, Any]) -> float:
    props = edge.get("properties") if isinstance(edge.get("properties"), dict) else {}
    raw = props.get("amount")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return 0.0
    return float(raw)


def _currency(edge: dict[str, Any]) -> str:
    props = edge.get("properties") if isinstance(edge.get("properties"), dict) else {}
    raw = props.get("currency")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return "USD"


def empty_mule_path(tenant_id: str, *, source: str = "graph") -> dict[str, Any]:
    return {
        "tenant_id": (tenant_id or "demo").strip() or "demo",
        "path_id": "",
        "updated_at": _now_iso(),
        "source": source,
        "hops": [],
        "transfers": [],
        "summary": {
            "hop_count": 0,
            "total_outflow": 0.0,
            "payout_amount": 0.0,
            "mule_retained": 0.0,
            "currency": "USD",
            "elapsed_hours": 0.0,
            "risk_flags": [],
        },
    }


def build_mule_path_from_edges(
    *,
    tenant_id: str,
    origin_entity_id: str,
    mule_entity_id: str | None,
    edges: list[dict[str, Any]],
) -> dict[str, Any]:
    origin = (origin_entity_id or "").strip()
    if not origin:
        return empty_mule_path(tenant_id)
    want_mule = (mule_entity_id or "").strip()
    matched: list[dict[str, Any]] = []
    for edge in edges:
        if not isinstance(edge, dict) or _edge_type(edge) != "TRANSACTED":
            continue
        src = _end(edge, "from_id", "startNode")
        dst = _end(edge, "to_id", "endNode")
        if src != origin or not dst or dst == origin:
            continue
        if want_mule and dst != want_mule:
            continue
        matched.append(edge)
    if not matched:
        return empty_mule_path(tenant_id)

    mules: list[str] = []
    for edge in matched:
        dst = _end(edge, "to_id", "endNode")
        if dst not in mules:
            mules.append(dst)
    hops: list[dict[str, Any]] = [
        {
            "role": "origin",
            "entity_id": origin,
            "label": origin,
            "node_type": "user",
            "description": "Person who sent the payment",
        }
    ]
    hops.extend(
        {
            "role": "mule",
            "entity_id": mule,
            "label": mule,
            "node_type": "user",
            "description": "TRANSACTED counterparty",
        }
        for mule in mules
    )
    transfers: list[dict[str, Any]] = []
    total = 0.0
    currency = _currency(matched[0])
    for index, edge in enumerate(matched):
        dst = _end(edge, "to_id", "endNode")
        amount = _amount(edge)
        total += amount
        props = edge.get("properties") if isinstance(edge.get("properties"), dict) else {}
        trace = str(props.get("trace_id") or edge.get("id") or index)
        transfers.append(
            {
                "id": f"xfer-{trace}",
                "from_role": "origin",
                "to_role": "mule",
                "from_entity_id": origin,
                "to_entity_id": dst,
                "amount": amount,
                "currency": _currency(edge),
                "trace_id": trace,
                "timestamp": str(props.get("timestamp") or ""),
                "channel": "payment",
                "status": "recorded",
            }
        )
    pid = hashlib.sha256(f"{tenant_id}|{origin}|{'|'.join(mules)}".encode()).hexdigest()[:16]
    return {
        "tenant_id": (tenant_id or "demo").strip() or "demo",
        "path_id": pid,
        "updated_at": _now_iso(),
        "source": "graph",
        "hops": hops,
        "transfers": transfers,
        "summary": {
            "hop_count": len(hops),
            "total_outflow": round(total, 2),
            "payout_amount": 0.0,
            "mule_retained": 0.0,
            "currency": currency,
            "elapsed_hours": 0.0,
            "risk_flags": ["transacted"] if transfers else [],
        },
    }


async def load_mule_path(
    *,
    tenant_id: str,
    origin_entity_id: str | None,
    mule_entity_id: str | None,
    graph_url: str | None = None,
) -> dict[str, Any]:
    origin = (origin_entity_id or "").strip()
    if not origin:
        return empty_mule_path(tenant_id)
    base = graph_url if graph_url is not None else os.environ.get("GRAPH_SERVICE_URL", "")
    base = base.strip()
    if not base:
        return empty_mule_path(tenant_id, source="graph:unconfigured")
    url = f"{base.rstrip('/')}/v1/entities/{quote(origin, safe='')}/links"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0, connect=1.0)) as client:
            response = await client.get(url, params={"tenant_id": tenant_id})
        if response.status_code == 404:
            return empty_mule_path(tenant_id)
        response.raise_for_status()
        body = response.json()
    except Exception:
        return empty_mule_path(tenant_id, source="graph:unavailable")
    edges = body.get("edges") if isinstance(body, dict) else None
    return build_mule_path_from_edges(
        tenant_id=tenant_id,
        origin_entity_id=origin,
        mule_entity_id=mule_entity_id,
        edges=edges if isinstance(edges, list) else [],
    )
