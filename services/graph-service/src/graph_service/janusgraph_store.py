from __future__ import annotations

import contextlib
import json
import logging
import re
from typing import Any

from gremlin_python.process.graph_traversal import __
from gremlin_python.process.traversal import Cardinality

from .custom_schema import get_allowed_labels, get_allowed_rels
from .entity_context_shape import shape_deep_context_from_nodes
from .entity_risk_score import _link_properties_with_observed_at, decorate_subgraph_node
from .hetero_schema import validate_typed_edge_or_raise
from .janusgraph_gremlin import get_traversal_source, run_in_gremlin_thread

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
    return decorate_subgraph_node({"id": str(vid), "labels": [str(lbl)], "properties": props})


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

    rel_props = _link_properties_with_observed_at(properties)
    trav = g.V(a[0]).addE(rel).to(__.V(b[0]))
    for pk, pv in rel_props.items():
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


def _list_one_hop_ids_sync(tenant_id: str, entity_id: str) -> list[str]:
    g = get_traversal_source()
    found = g.V().has("tenant_id", tenant_id).has("external_id", entity_id).limit(1).toList()
    if not found:
        return []
    raw = (
        g.V(found[0])
        .both()
        .has("tenant_id", tenant_id)
        .values("external_id")
        .dedup()
        .toList()
    )
    return [str(x) for x in raw if x]


async def list_one_hop_ids(tenant_id: str, entity_id: str) -> list[str]:
    return await run_in_gremlin_thread(lambda: _list_one_hop_ids_sync(tenant_id, entity_id))


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


def _query_entity_deep_context_sync(tenant_id: str, entity_id: str) -> dict[str, Any] | None:
    """Collect 2-hop neighborhood maps; return ``None`` when the root vertex is absent."""
    g = get_traversal_source()
    root_list = g.V().has("tenant_id", tenant_id).has("external_id", entity_id).limit(1).toList()
    if not root_list:
        return None
    root = root_list[0]
    maps_by_eid: dict[str, dict[str, Any]] = {}

    def capture(v: Any) -> None:
        try:
            omap = dict(g.V(v).elementMap().next())
        except StopIteration:
            return
        eid = str(omap.get("external_id") or "").strip()
        if eid:
            maps_by_eid[eid] = omap

    capture(root)
    frontier: list[tuple[Any, int]] = [(root, 0)]
    visited_vertex_ids = {root.id}

    while frontier:
        v, d = frontier.pop(0)
        if d >= 2:
            continue
        for e in g.V(v).bothE().toList():
            outv = e.outV().next()
            inv = e.inV().next()
            other = inv if outv.id == v.id else outv
            if other.id not in visited_vertex_ids:
                visited_vertex_ids.add(other.id)
                frontier.append((other, d + 1))
            capture(other)

    api_nodes = [_vertex_to_node(m) for m in maps_by_eid.values()]
    return shape_deep_context_from_nodes(entity_id, tenant_id, api_nodes)


async def query_entity_deep_context(tenant_id: str, entity_id: str) -> dict[str, Any] | None:
    return await run_in_gremlin_thread(
        lambda: _query_entity_deep_context_sync(tenant_id, entity_id)
    )


def _load_peer_p90_sync(tenant_id: str, label: str) -> int | None:
    from .graph_runtime import parse_p90_degree_by_label

    try:
        g = get_traversal_source()
        found = g.V().hasLabel("GraphRiskStats").has("tenant_id", tenant_id).limit(1).toList()
        if not found:
            return None
        raw = None
        with contextlib.suppress(Exception):
            raw = found[0].value("p90_degree_by_label")
        if raw is None:
            with contextlib.suppress(Exception):
                raw = g.V(found[0]).values("p90_degree_by_label").limit(1).next()
        return parse_p90_degree_by_label(raw, label)
    except Exception:
        return None


async def load_peer_p90_by_label(tenant_id: str, label: str) -> int | None:
    return await run_in_gremlin_thread(lambda: _load_peer_p90_sync(tenant_id, label))


def _set_entity_risk_properties_sync(tenant_id: str, entity_id: str, props: dict[str, Any]) -> None:
    g = get_traversal_source()
    found = g.V().has("tenant_id", tenant_id).has("external_id", entity_id).limit(1).toList()
    if not found:
        return
    v = found[0]
    trav = g.V(v)
    for key in (
        "risk_score",
        "risk_factors",
        "risk_computed_at",
        "relation_count",
        "relation_growth_1h",
        "relation_growth_24h",
    ):
        val = props.get(key)
        if val is None:
            continue
        if key == "risk_factors" or isinstance(val, (list, dict)):
            val = json.dumps(val)
        trav = trav.property(Cardinality.single, key, val)
    trav.iterate()


async def set_entity_risk_properties(tenant_id: str, entity_id: str, props: dict[str, Any]) -> None:
    await run_in_gremlin_thread(
        lambda: _set_entity_risk_properties_sync(tenant_id, entity_id, props)
    )


def _json_list(raw: Any) -> list:
    if raw is None:
        return []
    if isinstance(raw, list):
        return list(raw)
    if isinstance(raw, str):
        try:
            val = json.loads(raw)
            return list(val) if isinstance(val, list) else []
        except (TypeError, ValueError, json.JSONDecodeError):
            return [raw] if raw else []
    return [raw]


def _list_entity_risk_top_sync(
    tenant_id: str, limit: int, min_score: float
) -> list[dict[str, Any]]:
    from .entity_risk_writeback import clamp_top_limit

    limit = clamp_top_limit(limit)
    try:
        min_score = float(min_score)
    except (TypeError, ValueError):
        min_score = 0.0
    g = get_traversal_source()
    rows: list[dict[str, Any]] = []
    for v in g.V().has("tenant_id", tenant_id).toList():
        if str(getattr(v, "label", "") or "") == "GraphRiskStats":
            continue
        try:
            em = dict(g.V(v).elementMap().next())
        except StopIteration:
            continue
        computed = em.get("risk_computed_at")
        if computed is None or str(computed).strip() == "":
            continue
        try:
            score = float(em.get("risk_score") or 0)
        except (TypeError, ValueError):
            continue
        if score < min_score:
            continue
        lbl = em.get("label") or "Custom"
        if isinstance(lbl, list):
            lbl = lbl[0] if lbl else "Custom"
        rows.append(
            {
                "entity_id": str(em.get("external_id") or ""),
                "labels": [str(lbl)],
                "risk_score": score,
                "risk_factors": [str(x) for x in _json_list(em.get("risk_factors"))],
                "risk_computed_at": computed,
                "relation_count": int(em.get("relation_count") or 0),
                "relation_growth_1h": int(em.get("relation_growth_1h") or 0),
                "relation_growth_24h": int(em.get("relation_growth_24h") or 0),
            }
        )
    rows.sort(key=lambda r: (-float(r["risk_score"]), str(r["entity_id"])))
    return rows[:limit]


async def list_entity_risk_top(
    tenant_id: str, limit: int = 50, min_score: float = 0
) -> list[dict[str, Any]]:
    return await run_in_gremlin_thread(
        lambda: _list_entity_risk_top_sync(tenant_id, limit, min_score)
    )


def _scan_tenant_entity_ids_sync(tenant_id: str, limit: int) -> tuple[list[str], bool]:
    from .entity_risk_writeback import clamp_refresh_limit

    limit = clamp_refresh_limit(limit)
    g = get_traversal_source()
    ids: list[str] = []
    for v in g.V().has("tenant_id", tenant_id).toList():
        if str(getattr(v, "label", "") or "") == "GraphRiskStats":
            continue
        eid = _vertex_external_id(v)
        if eid:
            ids.append(eid)
    ids = sorted(set(ids))
    truncated = len(ids) > limit
    return ids[:limit], truncated


async def scan_tenant_entity_ids(tenant_id: str, limit: int) -> tuple[list[str], bool]:
    return await run_in_gremlin_thread(lambda: _scan_tenant_entity_ids_sync(tenant_id, limit))


def _upsert_graph_risk_stats_sync(
    tenant_id: str, p90_degree_by_label: dict[str, int], stats_computed_at: str
) -> None:
    g = get_traversal_source()
    raw = json.dumps(p90_degree_by_label or {})
    found = g.V().hasLabel("GraphRiskStats").has("tenant_id", tenant_id).limit(1).toList()
    if found:
        g.V(found[0]).property(Cardinality.single, "p90_degree_by_label", raw).property(
            Cardinality.single, "stats_computed_at", stats_computed_at
        ).iterate()
        return
    (
        g.addV("GraphRiskStats")
        .property("tenant_id", tenant_id)
        .property(Cardinality.single, "p90_degree_by_label", raw)
        .property(Cardinality.single, "stats_computed_at", stats_computed_at)
        .iterate()
    )


async def upsert_graph_risk_stats(
    tenant_id: str, p90_degree_by_label: dict[str, int], stats_computed_at: str
) -> None:
    await run_in_gremlin_thread(
        lambda: _upsert_graph_risk_stats_sync(tenant_id, p90_degree_by_label, stats_computed_at)
    )
