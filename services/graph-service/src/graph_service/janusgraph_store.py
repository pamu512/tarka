from __future__ import annotations

import json
import logging
import re
from typing import Any

from gremlin_python.process.graph_traversal import __
from gremlin_python.process.traversal import Cardinality

from graph_service.custom_schema import get_allowed_labels, get_allowed_rels
from graph_service.hetero_schema import validate_typed_edge_or_raise
from graph_service.janusgraph_gremlin import get_traversal_source, run_in_gremlin_thread

"""JanusGraph / Gremlin implementation of graph CRUD (same contract as neo4j_client)."""
log = logging.getLogger("graph-service.janus")

ALLOWED_LABELS = frozenset({"Person", "Account", "Device", "Payment", "Document", "Custom"})
ALLOWED_RELS = frozenset(
    {"USED", "SHARED_WITH", "REFERRED", "KYC_VERIFIED_BY", "OWNS", "CUSTOM", "RELATED"}
)
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


def _sanitize_label(label: str) -> str:
    if not _SAFE_IDENTIFIER.match(label):
        return "Custom"
    return label


def _sanitize_rel(rel: str) -> str:
    if not _SAFE_IDENTIFIER.match(rel):
        return "RELATED"
    return rel


def _tags_encode(tags: list[str] | None) -> str | None:
    if tags is None:
        return None
    return json.dumps(sorted(set(tags)))


def _tags_decode(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(t) for t in raw]
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            return [str(t) for t in data] if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _vertex_external_id(v: Any) -> str:
    try:
        return str(v.value("external_id"))
    except Exception:
        return ""


def _vertex_to_node(vm: dict) -> dict[str, Any]:
    """elementMap dict -> API node shape."""
    vid = vm.get("external_id") or str(vm.get("id", ""))
    lbl = vm.get("label") or "Custom"
    if isinstance(lbl, list):
        lbl = lbl[0] if lbl else "Custom"
    props = {k: v for k, v in vm.items() if k not in ("id", "label")}
    if "tags" in props:
        props = {**props, "tags": _tags_decode(props.get("tags"))}
    return {"id": str(vid), "labels": [str(lbl)], "properties": props}


def _upsert_entity_sync(
    tenant_id: str,
    entity_type: str,
    external_id: str,
    properties: dict[str, Any],
    tags: list[str] | None,
) -> str:
    g = get_traversal_source()
    tenant_labels = get_allowed_labels(tenant_id)
    label = entity_type if entity_type in (ALLOWED_LABELS | tenant_labels) else "Custom"
    label = _sanitize_label(label)
    props = {**properties, "tenant_id": tenant_id, "external_id": external_id}
    if tags is not None:
        props["tags"] = _tags_encode(tags) or "[]"

    def apply_props(trav, drop_tags_first: bool = False):
        t = trav
        if drop_tags_first:
            t = t.sideEffect(__.properties("tags").drop())
        for k, val in props.items():
            if val is None:
                continue
            if k == "tags":
                t = t.property(Cardinality.single, k, val)
            elif isinstance(val, (list, dict)):
                t = t.property(Cardinality.single, k, json.dumps(val))
            else:
                t = t.property(Cardinality.single, k, val)
        return t

    # Merge by tenant + external_id (any label); same external_id is unique per tenant.
    existing_list = (
        g.V().has("tenant_id", tenant_id).has("external_id", external_id).limit(1).toList()
    )
    if existing_list:
        v = existing_list[0]
        apply_props(g.V(v), drop_tags_first=True).iterate()
        return f"jvg:{tenant_id}:{external_id}"

    base = g.addV(label).property("tenant_id", tenant_id).property("external_id", external_id)
    apply_props(base, drop_tags_first=False).iterate()
    return f"jvg:{tenant_id}:{external_id}"


async def upsert_entity(
    tenant_id: str,
    entity_type: str,
    external_id: str,
    properties: dict[str, Any],
    tags: list[str] | None = None,
) -> str:
    return await run_in_gremlin_thread(
        lambda: _upsert_entity_sync(tenant_id, entity_type, external_id, properties, tags),
    )


def _update_tags_sync(tenant_id: str, external_id: str, tags: list[str]) -> list[str]:
    g = get_traversal_source()
    t = g.V().has("tenant_id", tenant_id).has("external_id", external_id).limit(1)
    if not t.hasNext():
        return tags
    v = t.next()
    cur = []
    try:
        raw = g.V(v).values("tags").limit(1).next()
        cur = _tags_decode(raw)
    except StopIteration:
        cur = []
    merged = sorted(set(cur) | set(tags))
    enc = json.dumps(merged)
    g.V(v).sideEffect(__.properties("tags").drop()).property(
        Cardinality.single, "tags", enc
    ).iterate()
    return merged


async def update_tags(tenant_id: str, external_id: str, tags: list[str]) -> list[str]:
    return await run_in_gremlin_thread(lambda: _update_tags_sync(tenant_id, external_id, tags))


def _get_tags_sync(tenant_id: str, external_id: str) -> list[str]:
    g = get_traversal_source()
    t = g.V().has("tenant_id", tenant_id).has("external_id", external_id).limit(1)
    if not t.hasNext():
        return []
    v = t.next()
    try:
        return _tags_decode(g.V(v).values("tags").limit(1).next())
    except StopIteration:
        return []


async def get_tags(tenant_id: str, external_id: str) -> list[str]:
    return await run_in_gremlin_thread(lambda: _get_tags_sync(tenant_id, external_id))


def _create_link_sync(
    tenant_id: str,
    from_external_id: str,
    to_external_id: str,
    relationship: str,
    properties: dict[str, Any],
) -> None:
    g = get_traversal_source()
    rel = relationship.upper().replace(" ", "_")
    tenant_rels = get_allowed_rels(tenant_id)
    if rel not in (ALLOWED_RELS | tenant_rels):
        rel = "RELATED"
    rel = _sanitize_rel(rel)

    a = g.V().has("tenant_id", tenant_id).has("external_id", from_external_id).limit(1).toList()
    b = g.V().has("tenant_id", tenant_id).has("external_id", to_external_id).limit(1).toList()
    if not a or not b:
        log.warning(
            "JanusGraph create_link: missing endpoint tenant=%s from=%s to=%s",
            tenant_id,
            from_external_id,
            to_external_id,
        )
        return

    try:
        la = str(g.V(a[0]).label().next())
        lb = str(g.V(b[0]).label().next())
    except StopIteration:
        la, lb = "Custom", "Custom"
    validate_typed_edge_or_raise(tenant_id, rel, [la], [lb])

    trav = g.V(a[0]).addE(rel).to(__.V(b[0]))
    for pk, pv in (properties or {}).items():
        if isinstance(pk, str) and _SAFE_IDENTIFIER.match(pk) and pv is not None:
            if isinstance(pv, (list, dict)):
                trav = trav.property(pk, json.dumps(pv))
            else:
                trav = trav.property(pk, pv)
    trav.iterate()


async def create_link(
    tenant_id: str,
    from_external_id: str,
    to_external_id: str,
    relationship: str,
    properties: dict[str, Any],
) -> None:
    await run_in_gremlin_thread(
        lambda: _create_link_sync(
            tenant_id,
            from_external_id,
            to_external_id,
            relationship,
            properties,
        ),
    )


def _query_subgraph_sync(tenant_id: str, entity_id: str, depth: int) -> dict[str, Any]:
    g = get_traversal_source()
    depth = max(1, min(int(depth), 5))

    root_list = g.V().has("tenant_id", tenant_id).has("external_id", entity_id).limit(1).toList()
    if not root_list:
        return {"nodes": [], "edges": []}
    root = root_list[0]

    nodes_out: list[dict[str, Any]] = []
    edges_out: list[dict[str, Any]] = []
    seen_edges: set[str] = set()
    seen_nodes: set[str] = set()

    def add_from_element_map(em: dict) -> None:
        eid = str(em.get("external_id", "") or "")
        if not eid or eid in seen_nodes:
            return
        seen_nodes.add(eid)
        nodes_out.append(_vertex_to_node(em))

    try:
        root_map = dict(g.V(root).elementMap().next())
        add_from_element_map(root_map)
    except StopIteration:
        return {"nodes": [], "edges": []}

    frontier = [(root, 0)]
    visited_vertex_ids = {root.id}

    while frontier:
        v, d = frontier.pop(0)
        if d >= depth:
            continue
        for e in g.V(v).bothE().toList():
            ekey = str(e.id)
            if ekey in seen_edges:
                continue
            outv = e.outV().next()
            inv = e.inV().next()
            other = inv if outv.id == v.id else outv
            if other.id not in visited_vertex_ids:
                visited_vertex_ids.add(other.id)
                frontier.append((other, d + 1))
            seen_edges.add(ekey)
            edges_out.append(
                {
                    "from_id": _vertex_external_id(outv),
                    "to_id": _vertex_external_id(inv),
                    "type": str(e.label),
                    "properties": {},
                },
            )
            try:
                omap = dict(g.V(other).elementMap().next())
                add_from_element_map(omap)
            except StopIteration:
                pass

    return {"nodes": nodes_out, "edges": edges_out}


async def query_subgraph(tenant_id: str, entity_id: str, depth: int) -> dict[str, Any]:
    return await run_in_gremlin_thread(lambda: _query_subgraph_sync(tenant_id, entity_id, depth))
