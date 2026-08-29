"""Evaluate-time subgraph receipt. Empty GRAPH_SERVICE_URL → graph:missing.

Identity is hop v1.2: unique (tenant_id, vtype, id). Role is a required
evaluate property on the user, not a vertex kind. Named edges keep their
type — unknown types are not rewritten to RELATED. party_graph is never
used as a stand-in graph.
"""

from __future__ import annotations

from typing import Any

from graph_contract import (
    BRIDGE_VTYPES,
    CORE_VTYPES,
    LEGACY_VTYPES,
    USER_VTYPE,
    roles_from_properties,
    vertex_key,
)

from decision_api.gnn_loop import SCHEMA_ID

_USER_VTYPES = frozenset({USER_VTYPE, "User", "Person", "Account"})
_KNOWN_VTYPES = frozenset(CORE_VTYPES | LEGACY_VTYPES)


def _blank_receipt(
    *,
    status: str,
    trace_id: str,
    entity_id: str,
    user_id: str,
    role: str,
    tenant_id: str = "",
) -> dict[str, Any]:
    return {
        "schema_id": SCHEMA_ID,
        "status": status,
        "tenant_id": str(tenant_id or ""),
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
        return [str(x).strip() for x in raw if str(x).strip()]
    props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    single = (
        node.get("label")
        or node.get("entity_type")
        or node.get("vtype")
        or props.get("vtype")
    )
    if single:
        return [str(single).strip()]
    return []


def _props(node: dict[str, Any]) -> dict[str, Any]:
    raw = node.get("properties")
    return raw if isinstance(raw, dict) else {}


def _node_id(node: dict[str, Any]) -> str:
    props = _props(node)
    return str(
        node.get("id") or node.get("external_id") or props.get("external_id") or ""
    ).strip()


def _tenant_of(node: dict[str, Any], fallback: str) -> str:
    props = _props(node)
    return str(
        node.get("tenant_id") or props.get("tenant_id") or fallback or ""
    ).strip()


def _vtype_of(node: dict[str, Any]) -> str:
    """Hop vtype. Role strings (diner/buyer/…) are not vertex kinds."""
    props = _props(node)
    for raw in (node.get("vtype"), props.get("vtype")):
        token = str(raw or "").strip()
        if token:
            return token
    for lab in _labels_of(node):
        if lab in _KNOWN_VTYPES or lab.lower() in BRIDGE_VTYPES:
            return lab.lower() if lab.lower() in BRIDGE_VTYPES else lab
    kind = str(node.get("kind") or "").strip().lower()
    if kind == "user":
        return USER_VTYPE
    if kind == "bridge":
        role = str(node.get("role") or "").strip().lower()
        if role in BRIDGE_VTYPES:
            return role
        for lab in _labels_of(node):
            if lab.lower() in BRIDGE_VTYPES:
                return lab.lower()
        return "device"
    return ""


def _kind_for_vtype(vtype: str) -> str | None:
    if vtype in _USER_VTYPES:
        return "user"
    if vtype.lower() in BRIDGE_VTYPES or vtype in {"Device", "Payment", "Document"}:
        return "bridge"
    return None


def _roles_of(
    node: dict[str, Any], *, evaluate_role: str, entity_id: str, vtype: str
) -> list[str]:
    props = _props(node)
    hop = roles_from_properties(props)
    extras: list[str] = []
    for raw in (node.get("role"), node.get("party_role"), props.get("party_role")):
        token = str(raw or "").strip().lower()
        if token and token not in BRIDGE_VTYPES and token not in _KNOWN_VTYPES:
            extras.append(token)
    prefix = (
        [evaluate_role]
        if evaluate_role and _node_id(node) == entity_id and vtype in _USER_VTYPES
        else []
    )
    seen: set[str] = set()
    out: list[str] = []
    for token in [*prefix, *hop, *extras]:
        t = str(token or "").strip().lower()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def filter_written_vertices(
    nodes: list[Any],
    *,
    tenant_id: str = "",
    entity_id: str = "",
    role: str = "",
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in nodes:
        if not isinstance(item, dict):
            continue
        nid = _node_id(item)
        vtype = _vtype_of(item)
        kind = _kind_for_vtype(vtype)
        if not nid or not vtype or kind is None:
            continue
        tid = _tenant_of(item, tenant_id)
        key = vertex_key(tid, vtype, nid)
        if key in seen:
            continue
        seen.add(key)
        roles = _roles_of(item, evaluate_role=role, entity_id=entity_id, vtype=vtype)
        vertex_role = (
            roles[0] if roles else (role if nid == entity_id and kind == "user" else "")
        )
        out.append(
            {
                "tenant_id": tid,
                "vtype": vtype,
                "id": nid,
                "kind": kind,
                "role": vertex_role,
                "roles": roles,
            }
        )
    return out


def filter_named_edges(edges: list[Any], kept_ids: set[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for item in edges:
        if not isinstance(item, dict):
            continue
        src = str(
            item.get("from_id")
            or item.get("src")
            or item.get("from")
            or item.get("source")
            or ""
        ).strip()
        dst = str(
            item.get("to_id")
            or item.get("dst")
            or item.get("to")
            or item.get("target")
            or ""
        ).strip()
        etype = str(
            item.get("type") or item.get("etype") or item.get("relationship") or ""
        ).strip()
        if not src or not dst or not etype:
            continue
        if src not in kept_ids or dst not in kept_ids:
            continue
        from_vtype = str(item.get("from_vtype") or "").strip()
        to_vtype = str(item.get("to_vtype") or "").strip()
        key = (from_vtype, src, etype, to_vtype, dst)
        if key in seen:
            continue
        seen.add(key)
        edge: dict[str, Any] = {
            "from_id": src,
            "to_id": dst,
            "type": etype,
            "src": src,
            "dst": dst,
        }
        if from_vtype:
            edge["from_vtype"] = from_vtype
        if to_vtype:
            edge["to_vtype"] = to_vtype
        out.append(edge)
    return out


def _named_edges_from_hop_blob(raw: dict[str, Any]) -> list[Any]:
    hop = raw.get("graph_risk") if isinstance(raw.get("graph_risk"), dict) else {}
    named = hop.get("named_edges") if isinstance(hop, dict) else None
    return named if isinstance(named, list) else []


def snapshot_from_written(
    raw: dict[str, Any] | None,
    *,
    trace_id: str,
    entity_id: str,
    user_id: str,
    role: str,
    tenant_id: str = "",
    status_if_empty: str = "graph:empty",
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return _blank_receipt(
            status=status_if_empty,
            trace_id=trace_id,
            entity_id=entity_id,
            user_id=user_id,
            role=role,
            tenant_id=tenant_id,
        )
    nodes = raw.get("nodes") if isinstance(raw.get("nodes"), list) else None
    if nodes is None:
        nodes = raw.get("vertices") if isinstance(raw.get("vertices"), list) else []
    edges_raw = raw.get("edges") if isinstance(raw.get("edges"), list) else []
    if not edges_raw:
        edges_raw = _named_edges_from_hop_blob(raw)
    vertices = filter_written_vertices(
        list(nodes), tenant_id=tenant_id, entity_id=entity_id, role=role
    )
    edges = filter_named_edges(list(edges_raw), {v["id"] for v in vertices})
    status = "graph:ok" if (vertices or edges) else status_if_empty
    return {
        "schema_id": SCHEMA_ID,
        "status": status,
        "tenant_id": str(tenant_id or ""),
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
    tenant_id: str = "",
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
            tenant_id=tenant_id,
        )
    if written_subgraph is None:
        return _blank_receipt(
            status="graph:unavailable",
            trace_id=trace_id,
            entity_id=entity_id,
            user_id=user_id,
            role=role,
            tenant_id=tenant_id,
        )
    return snapshot_from_written(
        written_subgraph,
        trace_id=trace_id,
        entity_id=entity_id,
        user_id=user_id,
        role=role,
        tenant_id=tenant_id,
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
    """Evaluate role only. Does not invent a role from party_graph."""
    _ = entity_id
    for src in (metadata, payload):
        if not isinstance(src, dict):
            continue
        raw = src.get("role") or src.get("party_role")
        if raw:
            return str(raw).strip().lower()[:64]
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
            tenant_id=tenant_id,
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
            tenant_id=tenant_id,
        )
