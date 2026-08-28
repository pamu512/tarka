"""Evaluate-time subgraph receipt. Empty GRAPH_SERVICE_URL → graph:missing."""

from __future__ import annotations

from typing import Any

from decision_api.gnn_loop import SCHEMA_ID
from decision_api.ring_score import _BRIDGE_ROLES, _PERSON_ROLES

_USER_LABELS = frozenset(
    {
        "account",
        "user",
        "person",
        *_PERSON_ROLES,
    }
)
_BRIDGE_LABELS = frozenset(
    {
        "device",
        "place",
        "promo",
        "payment",
        "paymentinstrument",
        "payment_instrument",
        *_BRIDGE_ROLES,
    }
)


def _blank_receipt(
    *,
    status: str,
    trace_id: str,
    entity_id: str,
    user_id: str,
    role: str,
) -> dict[str, Any]:
    return {
        "schema_id": SCHEMA_ID,
        "status": status,
        "trace_id": str(trace_id or ""),
        "entity_id": str(entity_id or ""),
        "user_id": str(user_id or entity_id or ""),
        "role": str(role or ""),
        "vertices": [],
        "edges": [],
    }


def _labels_of(node: dict[str, Any]) -> list[str]:
    raw = node.get("labels")
    if isinstance(raw, list):
        return [str(x).strip().lower() for x in raw if str(x).strip()]
    props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    single = node.get("label") or node.get("entity_type") or props.get("type")
    if single:
        return [str(single).strip().lower()]
    return []


def _role_of(node: dict[str, Any]) -> str:
    props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    for key in ("role", "party_role"):
        raw = node.get(key) or props.get(key)
        if raw:
            return str(raw).strip().lower()
    labels = _labels_of(node)
    for lab in labels:
        if lab in _PERSON_ROLES or lab in _BRIDGE_ROLES:
            return lab
        if lab in {"device"}:
            return "device"
        if lab in {"place"}:
            return "place"
        if lab in {"account", "user", "person"}:
            return "user"
    return ""


def _kind_for_node(node: dict[str, Any]) -> str | None:
    role = _role_of(node)
    labels = _labels_of(node)
    props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    if role in _PERSON_ROLES or any(lab in _USER_LABELS for lab in labels):
        return "user"
    if role in _BRIDGE_ROLES or any(
        lab.replace("-", "_") in _BRIDGE_LABELS for lab in labels
    ):
        return "bridge"
    if str(props.get("type") or "").strip().lower() == "session":
        return "bridge"
    kind = str(node.get("kind") or "").strip().lower()
    if kind in {"user", "bridge"}:
        return kind
    return None


def _node_id(node: dict[str, Any]) -> str:
    props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    return str(
        node.get("id") or node.get("external_id") or props.get("external_id") or ""
    ).strip()


def filter_written_vertices(nodes: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in nodes:
        if not isinstance(item, dict):
            continue
        nid = _node_id(item)
        kind = _kind_for_node(item)
        if not nid or kind is None or nid in seen:
            continue
        seen.add(nid)
        out.append({"id": nid, "kind": kind, "role": _role_of(item) or kind})
    return out


def filter_named_edges(edges: list[Any], kept_ids: set[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in edges:
        if not isinstance(item, dict):
            continue
        src = str(
            item.get("src")
            or item.get("from_id")
            or item.get("from")
            or item.get("source")
            or ""
        ).strip()
        dst = str(
            item.get("dst")
            or item.get("to_id")
            or item.get("to")
            or item.get("target")
            or ""
        ).strip()
        etype = str(item.get("type") or item.get("relationship") or "").strip().upper()
        if not src or not dst or not etype:
            continue
        if src not in kept_ids or dst not in kept_ids:
            continue
        key = (src, dst, etype)
        if key in seen:
            continue
        seen.add(key)
        out.append({"src": src, "dst": dst, "type": etype})
    return out


def snapshot_from_written(
    raw: dict[str, Any] | None,
    *,
    trace_id: str,
    entity_id: str,
    user_id: str,
    role: str,
    status_if_empty: str = "graph:empty",
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return _blank_receipt(
            status=status_if_empty,
            trace_id=trace_id,
            entity_id=entity_id,
            user_id=user_id,
            role=role,
        )
    nodes = raw.get("nodes") if isinstance(raw.get("nodes"), list) else None
    if nodes is None:
        nodes = raw.get("vertices") if isinstance(raw.get("vertices"), list) else []
    edges_raw = raw.get("edges") if isinstance(raw.get("edges"), list) else []
    vertices = filter_written_vertices(list(nodes))
    edges = filter_named_edges(list(edges_raw), {v["id"] for v in vertices})
    status = "graph:ok" if (vertices or edges) else status_if_empty
    return {
        "schema_id": SCHEMA_ID,
        "status": status,
        "trace_id": str(trace_id or ""),
        "entity_id": str(entity_id or ""),
        "user_id": str(user_id or entity_id or ""),
        "role": str(role or ""),
        "vertices": vertices,
        "edges": edges,
    }


def snapshot_at_evaluate(
    *,
    graph_service_url: str,
    trace_id: str,
    entity_id: str,
    user_id: str,
    role: str,
    written_subgraph: dict[str, Any] | None = None,
    party_graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Point-in-time receipt. ``party_graph`` is ignored when the graph URL is empty."""
    _ = party_graph  # host metadata is not a written graph
    if not (graph_service_url or "").strip():
        return _blank_receipt(
            status="graph:missing",
            trace_id=trace_id,
            entity_id=entity_id,
            user_id=user_id,
            role=role,
        )
    if written_subgraph is None:
        return _blank_receipt(
            status="graph:unavailable",
            trace_id=trace_id,
            entity_id=entity_id,
            user_id=user_id,
            role=role,
        )
    return snapshot_from_written(
        written_subgraph,
        trace_id=trace_id,
        entity_id=entity_id,
        user_id=user_id,
        role=role,
    )


async def fetch_written_subgraph(
    http: Any,
    graph_service_url: str,
    *,
    tenant_id: str,
    entity_id: str,
    depth: int = 2,
    timeout_seconds: float = 2.0,
) -> dict[str, Any] | None:
    """GET /v1/subgraph. Never invents neighbors. Returns None on any failure."""
    base = (graph_service_url or "").strip()
    if not base:
        return None
    try:
        response = await http.get(
            f"{base.rstrip('/')}/v1/subgraph",
            params={
                "tenant_id": tenant_id,
                "entity_id": entity_id,
                "depth": max(1, min(int(depth), 5)),
            },
            timeout=timeout_seconds,
        )
        raise_for_status = getattr(response, "raise_for_status", None)
        if callable(raise_for_status):
            maybe = raise_for_status()
            if hasattr(maybe, "__await__"):
                await maybe
        payload = response.json()
        if hasattr(payload, "__await__"):
            payload = await payload
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def role_from_evaluate(
    *,
    entity_id: str,
    payload: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
) -> str:
    for src in (metadata, payload):
        if not isinstance(src, dict):
            continue
        raw = src.get("role") or src.get("party_role")
        if raw:
            return str(raw).strip().lower()[:64]
        graph = src.get("party_graph")
        if isinstance(graph, dict) and isinstance(graph.get("nodes"), list):
            for node in graph["nodes"]:
                if isinstance(node, dict) and str(node.get("id") or "") == entity_id:
                    role = str(node.get("role") or "").strip().lower()
                    if role:
                        return role[:64]
    return ""


async def receipt_for_evaluate(
    http: Any,
    *,
    graph_service_url: str,
    tenant_id: str,
    entity_id: str,
    user_id: str,
    role: str,
    trace_id: str,
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fail-closed snapshot used by evaluate. Never raises to the caller."""
    try:
        resolved_role = role or role_from_evaluate(
            entity_id=entity_id, payload=payload, metadata=metadata
        )
        written = None
        if (graph_service_url or "").strip():
            written = await fetch_written_subgraph(
                http,
                graph_service_url,
                tenant_id=tenant_id,
                entity_id=entity_id,
            )
        return snapshot_at_evaluate(
            graph_service_url=graph_service_url,
            trace_id=trace_id,
            entity_id=entity_id,
            user_id=user_id,
            role=resolved_role,
            written_subgraph=written,
            party_graph=metadata.get("party_graph")
            if isinstance(metadata, dict)
            else None,
        )
    except Exception:
        return _blank_receipt(
            status="graph:missing"
            if not (graph_service_url or "").strip()
            else "graph:unavailable",
            trace_id=trace_id,
            entity_id=entity_id,
            user_id=user_id,
            role=role,
        )
