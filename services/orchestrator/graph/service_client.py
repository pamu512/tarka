"""Read graph signals from graph-service."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from graph.client import parse_graph_entity_ref
from graph_signals import SignalHop, compute_graph_signals, ip_velocity_block

_DEFAULT_GRAPH_SERVICE_URL = "http://graph-service:8001"
_CONTRACT_LABEL = {
    "user": "user",
    "User": "user",
    "Person": "user",
    "Account": "user",
    "device": "device",
    "Device": "device",
    "ip": "ip",
    "IP": "ip",
    "Ip": "ip",
    "payment": "payment",
    "Payment": "payment",
    "Card": "payment",
}


def graph_service_base_url() -> str:
    raw = (os.environ.get("GRAPH_SERVICE_URL") or _DEFAULT_GRAPH_SERVICE_URL).strip()
    return raw.rstrip("/") or _DEFAULT_GRAPH_SERVICE_URL


def _empty_signals(entity_id: str) -> dict[str, Any]:
    anchor, _ = parse_graph_entity_ref(entity_id)
    return {
        "entity_ref": entity_id.strip(),
        "anchor": anchor,
        "degree_centrality": {"total_distinct_neighbors": 0, "by_neighbor_label": {}},
        "two_hop_distinct_cards_last_2h": 0,
        "clustering": {
            "coefficient": 0.0,
            "accounts_sharing_three_devices": 0,
            "neighbor_user_count": 0,
        },
        "IP_VELOCITY": ip_velocity_block(distinct_users_last_2h=0),
        "backend": "none",
        "implemented": False,
        "status": "unavailable",
        "signals_usable": False,
        "signals_note": "graph backend disabled or not configured",
    }


def _node_id(node: dict[str, Any]) -> str:
    return str(node.get("id") or node.get("external_id") or "").strip()


def _node_label(node: dict[str, Any]) -> str:
    raw = node.get("entity_type") or node.get("vtype")
    if not raw:
        labels = node.get("labels") or node.get("label")
        if isinstance(labels, list):
            raw = labels[0] if labels else ""
        else:
            raw = labels
    token = str(raw or "").strip()
    return _CONTRACT_LABEL.get(token, token)


def _hops_from_subgraph(data: dict[str, Any]) -> list[SignalHop]:
    types: dict[str, str] = {}
    for node in data.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        ext = _node_id(node)
        if ext:
            types[ext] = _node_label(node)
    now = datetime.now(UTC)
    hops: list[SignalHop] = []
    for edge in data.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        src = str(edge.get("from_id") or edge.get("from_external_id") or "").strip()
        dst = str(edge.get("to_id") or edge.get("to_external_id") or "").strip()
        rel = str(edge.get("type") or edge.get("relationship") or "").strip()
        if not src or not dst or not rel:
            continue
        hops.append(
            SignalHop(
                src_label=types.get(src, ""),
                src_id=src,
                rel=rel,
                dst_label=types.get(dst, ""),
                dst_id=dst,
                observed_at=now,
            )
        )
    return hops


async def signals_for_entity(http: Any, *, tenant_id: str, entity_id: str) -> dict[str, Any]:
    url = f"{graph_service_base_url()}/v1/subgraph"
    params = {"entity_id": entity_id, "tenant_id": tenant_id, "depth": 2}
    try:
        response = await http.get(url, params=params)
    except Exception:
        return _empty_signals(entity_id)
    status = getattr(response, "status_code", None)
    if status != 200:
        return _empty_signals(entity_id)
    try:
        data = response.json()
    except Exception:
        return _empty_signals(entity_id)
    if not isinstance(data, dict):
        return _empty_signals(entity_id)
    anchor, ref = parse_graph_entity_ref(entity_id)
    return compute_graph_signals(anchor, ref, _hops_from_subgraph(data))
