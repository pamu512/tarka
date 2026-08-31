"""Graph + evaluate hop contract v1.2.

One ontology. Identity is (tenant_id, vtype, id). Role is a registered string
on user vertices (roles[]). Unknown vtype/etype/role is refused — never rewritten
to RELATED / Custom. Multi-id is derived from shared bridges, not written
SHARES_*/SAME_AS/RELATED edges.

This module is the unit-testable source of truth. Stores (Janus/Neo4j/AGE)
and decision-api evaluate must call these helpers; they must not invent a
second identity key or sanitize unknown edges to RELATED.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

SCHEMA_ID = "tarka.graph_contract/v1.2"

USER_VTYPE = "user"
BRIDGE_VTYPES = frozenset({"device", "ip", "phone", "payment", "place", "promo", "order"})
CORE_VTYPES = frozenset({USER_VTYPE}) | BRIDGE_VTYPES

# Registered write etypes. RELATED is not a rewrite target and is not written
# for identity/multi-id answers.
CORE_ETYPES = frozenset(
    {
        "USED",
        "SEEN_AT",
        "PARTY_WITH",
        "OWNS",
        "REFERRED",
        "KYC_VERIFIED_BY",
        "USED_DEVICE",
        "USED_SESSION",
        "USED_IP",
        "MADE_PAYMENT",
        "PERFORMED_LOGIN",
    }
)

# Legacy labels tenants may still register. Not a second identity system.
LEGACY_VTYPES = frozenset(
    {
        "Person",
        "Account",
        "Device",
        "Payment",
        "Document",
        "Decision",
        "Custom",
        "User",
        "Login",
        "Session",
        "Ip",
        "LicensePlate",
    }
)

_SAFE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_ROLE_SAFE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")

# tenant_id -> registered extras (vtypes, etypes, roles)
_tenant_vtypes: dict[str, set[str]] = {}
_tenant_etypes: dict[str, set[str]] = {}
_tenant_roles: dict[str, set[str]] = {}


class UnsignedGraphToken(ValueError):
    """vtype, etype, or role is not in the tenant registry."""

    def __init__(self, kind: str, token: str, *, tenant_id: str = "") -> None:
        self.kind = kind
        self.token = token
        self.tenant_id = tenant_id
        super().__init__(f"unsigned {kind}: {token}")


def reset_tenant_registry(tenant_id: str | None = None) -> None:
    if tenant_id is None:
        _tenant_vtypes.clear()
        _tenant_etypes.clear()
        _tenant_roles.clear()
        return
    _tenant_vtypes.pop(tenant_id, None)
    _tenant_etypes.pop(tenant_id, None)
    _tenant_roles.pop(tenant_id, None)


def register_vtypes(tenant_id: str, vtypes: Iterable[str]) -> None:
    bag = _tenant_vtypes.setdefault(tenant_id, set())
    for raw in vtypes:
        token = _norm_vtype(raw)
        if not _SAFE.fullmatch(token):
            raise UnsignedGraphToken("vtype", raw, tenant_id=tenant_id)
        bag.add(token)


def register_etypes(tenant_id: str, etypes: Iterable[str]) -> None:
    bag = _tenant_etypes.setdefault(tenant_id, set())
    for raw in etypes:
        token = _norm_etype(raw)
        if not _SAFE.fullmatch(token):
            raise UnsignedGraphToken("etype", raw, tenant_id=tenant_id)
        bag.add(token)


def register_roles(tenant_id: str, roles: Iterable[str]) -> None:
    bag = _tenant_roles.setdefault(tenant_id, set())
    for raw in roles:
        token = _norm_role(raw)
        if not token or not _ROLE_SAFE.fullmatch(token):
            raise UnsignedGraphToken("role", raw, tenant_id=tenant_id)
        bag.add(token)


def registered_vtypes(tenant_id: str) -> frozenset[str]:
    extra = _tenant_vtypes.get(tenant_id) or set()
    return frozenset(CORE_VTYPES | LEGACY_VTYPES | extra)


def registered_etypes(tenant_id: str) -> frozenset[str]:
    extra = _tenant_etypes.get(tenant_id) or set()
    return frozenset(CORE_ETYPES | extra)


def registered_roles(tenant_id: str) -> frozenset[str]:
    return frozenset(_tenant_roles.get(tenant_id) or set())


def _norm_vtype(raw: str) -> str:
    return str(raw or "").strip()


def _norm_etype(raw: str) -> str:
    return str(raw or "").strip().upper().replace(" ", "_").replace("-", "_")


def _norm_role(raw: str) -> str:
    return str(raw or "").strip().lower()


def require_vtype(tenant_id: str, vtype: str) -> str:
    token = _norm_vtype(vtype)
    if not token or not _SAFE.fullmatch(token) or token not in registered_vtypes(tenant_id):
        raise UnsignedGraphToken("vtype", vtype, tenant_id=tenant_id)
    return token


def require_etype(tenant_id: str, etype: str) -> str:
    token = _norm_etype(etype)
    if not token or not _SAFE.fullmatch(token) or token not in registered_etypes(tenant_id):
        raise UnsignedGraphToken("etype", etype, tenant_id=tenant_id)
    return token


def require_role(tenant_id: str, role: str) -> str:
    token = _norm_role(role)
    if not token or not _ROLE_SAFE.fullmatch(token):
        raise UnsignedGraphToken("role", role, tenant_id=tenant_id)
    locked = registered_roles(tenant_id)
    # ponytail: empty registry is open (tenant has not locked roles). Closed set once any role is registered.
    if locked and token not in locked:
        raise UnsignedGraphToken("role", role, tenant_id=tenant_id)
    return token


def vertex_key(tenant_id: str, vtype: str, entity_id: str) -> tuple[str, str, str]:
    return (str(tenant_id), str(vtype), str(entity_id))


def janus_graph_id(tenant_id: str, vtype: str, entity_id: str) -> str:
    return f"jvg:{tenant_id}:{vtype}:{entity_id}"


def merge_roles(existing: Iterable[str] | None, incoming: Iterable[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in list(existing or []) + list(incoming or []):
        token = _norm_role(str(raw))
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def roles_from_properties(properties: dict[str, Any] | None) -> list[str]:
    props = properties if isinstance(properties, dict) else {}
    incoming: list[str] = []
    raw_list = props.get("roles")
    if isinstance(raw_list, list):
        incoming.extend(str(x) for x in raw_list)
    elif isinstance(raw_list, str) and raw_list.strip():
        incoming.append(raw_list)
    one = props.get("role")
    if isinstance(one, str) and one.strip():
        incoming.append(one)
    return merge_roles([], incoming)


def _labels_of(node: dict[str, Any]) -> list[str]:
    raw = node.get("labels") or node.get("label") or node.get("vtype")
    if isinstance(raw, list):
        return [str(x) for x in raw if str(x).strip()]
    if raw:
        return [str(raw)]
    return []


def _node_id(node: dict[str, Any]) -> str:
    return str(node.get("id") or node.get("external_id") or node.get("entity_id") or "").strip()


def _is_user_node(node: dict[str, Any]) -> bool:
    labels = {str(x) for x in _labels_of(node)}
    return bool(labels & {USER_VTYPE, "User", "Person", "Account"})


def _is_bridge_node(node: dict[str, Any]) -> bool:
    labels = {str(x).lower() for x in _labels_of(node)}
    return bool(labels & (BRIDGE_VTYPES | {"session", "document", "licenseplate"}))


def graph_answers_from_neighborhood(
    subject_id: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, Any]:
    """Derive evaluate graph answers. Does not invent edges."""
    sid = str(subject_id or "").strip()
    by_id: dict[str, dict[str, Any]] = {}
    for n in nodes or []:
        nid = _node_id(n)
        if nid:
            by_id[nid] = n

    subject = by_id.get(sid)
    roles = roles_from_properties((subject or {}).get("properties") if subject else None)
    if subject and not roles:
        roles = merge_roles([], [str(subject.get("role") or "")])

    named_edges: list[dict[str, str]] = []
    for e in edges or []:
        if not isinstance(e, dict):
            continue
        et = str(
            e.get("type") or e.get("rel") or e.get("etype") or e.get("relationship") or ""
        ).strip()
        src = str(
            e.get("from_id") or e.get("src") or e.get("from") or e.get("from_external_id") or ""
        ).strip()
        dst = str(
            e.get("to_id") or e.get("dst") or e.get("to") or e.get("to_external_id") or ""
        ).strip()
        if not et or not src or not dst:
            continue
        named_edges.append({"from_id": src, "to_id": dst, "type": et})

    # Multi-id: other user vertices that share a bridge (device/ip/phone/payment).
    adj: dict[str, set[str]] = {}
    for e in named_edges:
        adj.setdefault(e["from_id"], set()).add(e["to_id"])
        adj.setdefault(e["to_id"], set()).add(e["from_id"])

    multi: list[str] = []
    seen_multi: set[str] = set()
    for nbr_id in adj.get(sid, ()):
        nbr = by_id.get(nbr_id)
        if nbr is None or not _is_bridge_node(nbr):
            # Also treat lowercase id collision: label on node
            labs = {str(x).lower() for x in _labels_of(nbr or {})}
            if not (labs & BRIDGE_VTYPES):
                continue
        for other_id in adj.get(nbr_id, ()):
            if other_id == sid or other_id in seen_multi:
                continue
            other = by_id.get(other_id)
            if other is None or not _is_user_node(other):
                continue
            seen_multi.add(other_id)
            multi.append(other_id)

    return {
        "roles": roles,
        "multi_id_user_ids": sorted(multi),
        "named_edges": named_edges,
    }


def empty_graph_answers() -> dict[str, Any]:
    return {"roles": [], "multi_id_user_ids": [], "named_edges": []}


def consume_graph_answers(graph_meta: dict[str, Any] | None) -> dict[str, Any]:
    """Lift named edges / multi-id / roles from an entity-risk blob. No invention."""
    if not isinstance(graph_meta, dict):
        return empty_graph_answers()
    edges_raw = graph_meta.get("named_edges")
    named: list[dict[str, str]] = []
    if isinstance(edges_raw, list):
        for e in edges_raw:
            if not isinstance(e, dict):
                continue
            et = str(
                e.get("type") or e.get("rel") or e.get("etype") or e.get("relationship") or ""
            ).strip()
            src = str(
                e.get("from_id") or e.get("src") or e.get("from") or e.get("from_external_id") or ""
            ).strip()
            dst = str(
                e.get("to_id") or e.get("dst") or e.get("to") or e.get("to_external_id") or ""
            ).strip()
            if et and src and dst:
                named.append({"from_id": src, "to_id": dst, "type": et})
    roles = graph_meta.get("roles")
    role_list = [str(x).strip() for x in roles] if isinstance(roles, list) else []
    mid = graph_meta.get("multi_id_user_ids")
    multi = [str(x).strip() for x in mid if str(x).strip()] if isinstance(mid, list) else []
    return {
        "roles": [x for x in role_list if x],
        "multi_id_user_ids": multi,
        "named_edges": named,
    }


def pack_why_from_graph_answers(answers: dict[str, Any] | None) -> dict[str, Any]:
    a = answers if isinstance(answers, dict) else empty_graph_answers()
    return {
        "named_edges": list(a.get("named_edges") or []),
        "multi_id_user_ids": list(a.get("multi_id_user_ids") or []),
        "roles": list(a.get("roles") or []),
        "invented_edges": False,
    }


class MemoryGraph:
    """In-process graph used by contract tests. Same identity/refuse rules as stores."""

    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        self._vertices: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._edges: list[dict[str, Any]] = []

    def upsert(
        self,
        vtype: str,
        entity_id: str,
        *,
        properties: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> str:
        label = require_vtype(self.tenant_id, vtype)
        eid = str(entity_id).strip()
        if not eid:
            raise ValueError("entity_id required")
        key = vertex_key(self.tenant_id, label, eid)
        prev = self._vertices.get(key)
        props = dict(properties or {})
        incoming_roles = roles_from_properties(props)
        if prev is not None:
            old_roles = roles_from_properties(prev.get("properties"))
            props["roles"] = merge_roles(old_roles, incoming_roles)
            merged_props = {**(prev.get("properties") or {}), **props}
            merged_props["roles"] = props["roles"]
            prev["properties"] = merged_props
            if tags is not None:
                prev["tags"] = list(tags)
            return janus_graph_id(self.tenant_id, label, eid)
        props["roles"] = incoming_roles
        props["tenant_id"] = self.tenant_id
        props["external_id"] = eid
        self._vertices[key] = {
            "id": eid,
            "labels": [label],
            "properties": props,
            "tags": list(tags or []),
        }
        return janus_graph_id(self.tenant_id, label, eid)

    def get(self, vtype: str, entity_id: str) -> dict[str, Any] | None:
        return self._vertices.get(vertex_key(self.tenant_id, vtype, entity_id))

    def vertices_for_id(self, entity_id: str) -> list[dict[str, Any]]:
        eid = str(entity_id)
        return [v for (_t, _vt, i), v in self._vertices.items() if i == eid]

    def create_link(
        self,
        from_id: str,
        to_id: str,
        etype: str,
        *,
        from_vtype: str | None = None,
        to_vtype: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> None:
        rel = require_etype(self.tenant_id, etype)
        a = self._resolve_endpoint(from_id, from_vtype)
        b = self._resolve_endpoint(to_id, to_vtype)
        self._edges.append(
            {
                "from_id": a["id"],
                "to_id": b["id"],
                "type": rel,
                "from_vtype": _labels_of(a)[0] if _labels_of(a) else "",
                "to_vtype": _labels_of(b)[0] if _labels_of(b) else "",
                "properties": dict(properties or {}),
            }
        )

    def _resolve_endpoint(self, entity_id: str, vtype: str | None) -> dict[str, Any]:
        if vtype:
            node = self.get(require_vtype(self.tenant_id, vtype), entity_id)
            if node is None:
                raise ValueError(f"missing endpoint {vtype}:{entity_id}")
            return node
        hits = self.vertices_for_id(entity_id)
        if not hits:
            raise ValueError(f"missing endpoint {entity_id}")
        if len(hits) > 1:
            raise ValueError(f"ambiguous endpoint {entity_id}: specify vtype")
        return hits[0]

    def subgraph(
        self, entity_id: str, *, vtype: str = USER_VTYPE, depth: int = 2
    ) -> dict[str, Any]:
        root = self.get(vtype, entity_id)
        if root is None:
            return {"nodes": [], "edges": []}
        depth = max(1, min(int(depth), 5))
        seen = {entity_id}
        nodes = [root]
        edges: list[dict[str, Any]] = []
        frontier = {entity_id}
        for _ in range(depth):
            nxt: set[str] = set()
            for e in self._edges:
                if e["from_id"] in frontier or e["to_id"] in frontier:
                    edges.append(e)
                    for oid in (e["from_id"], e["to_id"]):
                        if oid in seen:
                            continue
                        seen.add(oid)
                        nxt.add(oid)
                        hits = self.vertices_for_id(oid)
                        nodes.extend(hits)
            frontier = nxt
        return {"nodes": nodes, "edges": edges}

    def entity_risk_answers(self, entity_id: str, *, vtype: str = USER_VTYPE) -> dict[str, Any]:
        sub = self.subgraph(entity_id, vtype=vtype)
        return graph_answers_from_neighborhood(entity_id, sub["nodes"], sub["edges"])
