from __future__ import annotations

import contextlib
import json
import logging
import re
from typing import Any

from gremlin_python.process.graph_traversal import __
from gremlin_python.process.traversal import Cardinality, P, T

from .config import settings
from .custom_schema import get_allowed_labels, get_allowed_rels
from .entity_context_shape import shape_deep_context_from_nodes
from .entity_risk_score import (
    _link_properties_with_observed_at,
    decorate_subgraph_node,
)
from .hetero_schema import validate_typed_edge_or_raise
from graph_contract import (
    USER_VTYPE,
    UnsignedGraphToken,
    janus_graph_id,
    merge_roles,
    require_etype,
    require_vtype,
    roles_from_properties,
)
from .janusgraph_gremlin import (
    get_traversal_source,
    run_in_gremlin_thread,
    vertex_search_index_enabled,
)

"""JanusGraph / Gremlin implementation of graph CRUD (same contract as neo4j_client)."""
log = logging.getLogger("graph-service.janus")

ALLOWED_LABELS = frozenset(
    {"user", "device", "ip", "phone", "payment", "place", "promo", "order"}
)
ALLOWED_RELS = frozenset(
    {"USED", "SEEN_AT", "PARTY_WITH", "OWNS", "REFERRED", "KYC_VERIFIED_BY"}
)
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


def refuse_label(tenant_id: str, label: str) -> str:
    """Refuse unsigned vtypes. Never rewrite to Custom."""
    return require_vtype(tenant_id, label)


def refuse_rel(tenant_id: str, rel: str) -> str:
    """Refuse unsigned etypes. Never rewrite to RELATED."""
    return require_etype(tenant_id, rel)


def vertex_lookup_uses_label() -> bool:
    return True


def janus_graph_id_for(tenant_id: str, vtype: str, entity_id: str) -> str:
    return janus_graph_id(tenant_id, vtype, entity_id)


def _sanitize_label(label: str) -> str:
    if not _SAFE_IDENTIFIER.match(label):
        raise UnsignedGraphToken("vtype", label)
    return label


def _sanitize_rel(rel: str) -> str:
    if not _SAFE_IDENTIFIER.match(rel):
        raise UnsignedGraphToken("etype", rel)
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


def _valuemap_to_element(vm: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (vm or {}).items():
        if k in (T.id, "id") or str(k) in ("id", "T.id"):
            out["id"] = v
            continue
        if k in (T.label, "label") or str(k) in ("label", "T.label"):
            out["label"] = v[0] if isinstance(v, list) and v else v
            continue
        key = str(k)
        if isinstance(v, (list, tuple)):
            out[key] = v[0] if len(v) == 1 else list(v)
        else:
            out[key] = v
    return out


def _labels_from_em(em: dict[str, Any]) -> list[str]:
    raw_lbl = em.get("label")
    if isinstance(raw_lbl, list):
        return [str(x) for x in raw_lbl] if raw_lbl else ["Custom"]
    return [str(raw_lbl or "Custom")]


def _batch_valuemap(g: Any, vertices: list[Any]) -> list[dict[str, Any]]:
    if not vertices:
        return []
    raw = g.V(*vertices).valueMap(True).toList()
    return [_valuemap_to_element(m) for m in raw]


def _upsert_entity_sync(
    tenant_id: str,
    entity_type: str,
    external_id: str,
    properties: dict[str, Any],
    tags: list[str] | None,
) -> str:
    g = get_traversal_source()
    get_allowed_labels(tenant_id)
    label = refuse_label(tenant_id, entity_type)
    label = _sanitize_label(label)
    incoming_roles = roles_from_properties(properties)
    props = {**properties, "tenant_id": tenant_id, "external_id": external_id, "vtype": label}
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

    # Identity is (tenant_id, vtype, id). user:abc and device:abc are different vertices.
    existing_list = (
        g.V()
        .hasLabel(label)
        .has("tenant_id", tenant_id)
        .has("external_id", external_id)
        .limit(1)
        .toList()
    )
    if existing_list:
        v = existing_list[0]
        old_roles: list[str] = []
        with contextlib.suppress(Exception):
            raw_roles = g.V(v).values("roles").limit(1).next()
            if isinstance(raw_roles, str):
                try:
                    parsed = json.loads(raw_roles)
                    old_roles = [str(x) for x in parsed] if isinstance(parsed, list) else [raw_roles]
                except json.JSONDecodeError:
                    old_roles = [raw_roles]
            elif isinstance(raw_roles, list):
                old_roles = [str(x) for x in raw_roles]
        props["roles"] = merge_roles(old_roles, incoming_roles)
        apply_props(g.V(v), drop_tags_first=True).iterate()
        return janus_graph_id(tenant_id, label, external_id)
    props["roles"] = incoming_roles

    base = (
        g.addV(label)
        .property("tenant_id", tenant_id)
        .property("external_id", external_id)
        .property("vtype", label)
    )
    apply_props(base, drop_tags_first=False).iterate()
    return janus_graph_id(tenant_id, label, external_id)


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
    get_allowed_rels(tenant_id)
    rel = refuse_rel(tenant_id, relationship)
    rel = _sanitize_rel(rel)

    from_vtype = (properties or {}).get("from_vtype") or (properties or {}).get("from_entity_type")
    to_vtype = (properties or {}).get("to_vtype") or (properties or {}).get("to_entity_type")
    a_trav = g.V().has("tenant_id", tenant_id).has("external_id", from_external_id)
    b_trav = g.V().has("tenant_id", tenant_id).has("external_id", to_external_id)
    if from_vtype:
        a_trav = a_trav.hasLabel(str(from_vtype))
    if to_vtype:
        b_trav = b_trav.hasLabel(str(to_vtype))
    a = a_trav.limit(2).toList()
    b = b_trav.limit(2).toList()
    if len(a) > 1 or len(b) > 1:
        raise ValueError("ambiguous endpoint: specify from_vtype/to_vtype")
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

    rel_props = _link_properties_with_observed_at(
        {
            k: v
            for k, v in (properties or {}).items()
            if k not in ("from_vtype", "to_vtype", "from_entity_type", "to_entity_type")
        }
    )
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
    raw = g.V(found[0]).both().has("tenant_id", tenant_id).values("external_id").dedup().toList()
    return [str(x) for x in raw if x]


async def list_one_hop_ids(tenant_id: str, entity_id: str) -> list[str]:
    return await run_in_gremlin_thread(lambda: _list_one_hop_ids_sync(tenant_id, entity_id))


def _walk_incident_layers(
    g: Any, root: Any, depth: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """One Gremlin round-trip per depth layer. Super-node RAM is a known ceiling (no per-vertex edge cap)."""
    depth = max(1, min(int(depth), 5))
    nodes_out: list[dict[str, Any]] = []
    edges_out: list[dict[str, Any]] = []
    seen_edges: set[str] = set()
    seen_nodes: set[str] = set()

    def add_em(em: dict[str, Any]) -> None:
        eid = str(em.get("external_id", "") or "")
        if not eid or eid in seen_nodes:
            return
        seen_nodes.add(eid)
        nodes_out.append(_vertex_to_node(em))

    root_maps = _batch_valuemap(g, [root])
    if not root_maps:
        return [], []
    add_em(root_maps[0])

    frontier: list[Any] = [root]
    visited: set[Any] = {getattr(root, "id", root)}
    for _layer in range(depth):
        if not frontier:
            break
        rows = (
            g.V(*frontier)
            .bothE()
            .as_("e")
            .otherV()
            .as_("o")
            .project("eid", "elabel", "from_ext", "to_ext", "oid", "omap")
            .by(__.select("e").id())
            .by(__.select("e").label())
            .by(__.select("e").outV().values("external_id"))
            .by(__.select("e").inV().values("external_id"))
            .by(__.select("o").id())
            .by(__.select("o").valueMap(True))
            .toList()
        )
        next_frontier: list[Any] = []
        next_seen: set[Any] = set()
        for row in rows or []:
            ekey = str(row.get("eid"))
            if ekey in seen_edges:
                continue
            seen_edges.add(ekey)
            edges_out.append(
                {
                    "from_id": str(row.get("from_ext") or ""),
                    "to_id": str(row.get("to_ext") or ""),
                    "type": str(row.get("elabel") or ""),
                    "properties": {},
                }
            )
            oid = row.get("oid")
            if oid not in visited and oid not in next_seen:
                visited.add(oid)
                next_seen.add(oid)
                next_frontier.append(oid)
            omap = row.get("omap")
            if isinstance(omap, dict):
                add_em(_valuemap_to_element(omap))
        frontier = next_frontier
    return nodes_out, edges_out


def _query_subgraph_sync(tenant_id: str, entity_id: str, depth: int) -> dict[str, Any]:
    g = get_traversal_source()
    depth = max(1, min(int(depth), 5))
    root_list = (
        g.V()
        .hasLabel(USER_VTYPE)
        .has("tenant_id", tenant_id)
        .has("external_id", entity_id)
        .limit(1)
        .toList()
    )
    if not root_list:
        # Legacy single-vertex id (Person/Account) — still do not merge across labels.
        hits = g.V().has("tenant_id", tenant_id).has("external_id", entity_id).limit(2).toList()
        root_list = hits[:1] if len(hits) == 1 else []
    if not root_list:
        return {"nodes": [], "edges": []}
    nodes_out, edges_out = _walk_incident_layers(g, root_list[0], depth)
    return {"nodes": nodes_out, "edges": edges_out}


async def query_subgraph(tenant_id: str, entity_id: str, depth: int) -> dict[str, Any]:
    return await run_in_gremlin_thread(lambda: _query_subgraph_sync(tenant_id, entity_id, depth))


def _query_entity_deep_context_sync(tenant_id: str, entity_id: str) -> dict[str, Any] | None:
    """Collect 2-hop neighborhood maps; return ``None`` when the root vertex is absent."""
    g = get_traversal_source()
    root_list = (
        g.V()
        .hasLabel(USER_VTYPE)
        .has("tenant_id", tenant_id)
        .has("external_id", entity_id)
        .limit(1)
        .toList()
    )
    if not root_list:
        hits = g.V().has("tenant_id", tenant_id).has("external_id", entity_id).limit(2).toList()
        root_list = hits[:1] if len(hits) == 1 else []
    if not root_list:
        return None
    nodes_out, _edges = _walk_incident_layers(g, root_list[0], 2)
    return shape_deep_context_from_nodes(entity_id, tenant_id, nodes_out)


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


async def search_entities(
    tenant_id: str, q: str, label: str | None = None, limit: int = 20
) -> tuple[list[dict[str, Any]], bool]:
    from .entity_risk_score import (
        SEARCH_PROP_KEYS,
        cap_identifier_owners,
        clamp_search_limit,
        eligible_search_node_prefix,
        labels_are_identifier,
        labels_are_owner,
        merge_search_hits,
        search_hit_from_node,
    )

    limit = clamp_search_limit(limit)
    needle = str(q or "")

    def _capped_scan(g: Any) -> tuple[list[Any], bool]:
        cap = int(settings.janusgraph_analytics_vertex_cap)
        found = g.V().has("tenant_id", tenant_id).limit(cap).toList()
        return found, len(found) >= cap

    def _search_entities_sync() -> tuple[list[dict[str, Any]], bool]:
        g = get_traversal_source()
        truncated = False
        vertices: list[Any] = []
        if vertex_search_index_enabled():
            try:
                seen: set[Any] = set()
                for field in SEARCH_PROP_KEYS:
                    found = (
                        g.V()
                        .has("tenant_id", tenant_id)
                        .has(field, P("textContainsPrefix", needle))
                        .limit(50)
                        .toList()
                    )
                    for v in found:
                        vid = getattr(v, "id", v)
                        if vid in seen:
                            continue
                        seen.add(vid)
                        vertices.append(v)
            except Exception:
                log.exception("Janus textContainsPrefix failed; using capped tenant scan")
                vertices, truncated = _capped_scan(g)
        else:
            vertices, truncated = _capped_scan(g)

        maps = _batch_valuemap(g, vertices)
        directs: list[dict[str, Any]] = []
        ident_vs: list[tuple[str, dict[str, Any], Any]] = []
        for v, em in zip(vertices, maps):
            if str(em.get("label") or "") == "GraphRiskStats":
                continue
            eid = str(em.get("external_id") or "").strip()
            labels = _labels_from_em(em)
            props = {k: val for k, val in em.items() if k not in ("id", "label")}
            matched = eligible_search_node_prefix(eid, props, needle)
            if not matched:
                continue
            hit = search_hit_from_node(tenant_id, eid, labels, props, matched_on=matched, via=None)
            directs.append(hit)
            if labels_are_identifier(labels):
                ident_vs.append((eid, hit, v))

        owner_meta: list[tuple[Any, dict[str, Any]]] = []
        for _eid, ident, v in ident_vs:
            for nv in g.V(v).both().limit(10).toList():
                owner_meta.append((nv, ident))
        unique_owners: list[Any] = []
        seen_n: set[Any] = set()
        for nv, _ident in owner_meta:
            nid = getattr(nv, "id", None)
            if nid in seen_n:
                continue
            seen_n.add(nid)
            unique_owners.append(nv)
        hydrated = {
            getattr(nv, "id", None): em
            for nv, em in zip(unique_owners, _batch_valuemap(g, unique_owners))
        }
        raw_owners: list[dict[str, Any]] = []
        for nv, ident in owner_meta:
            em = hydrated.get(getattr(nv, "id", None))
            if not em:
                continue
            oid = str(em.get("external_id") or "").strip()
            olabels = _labels_from_em(em)
            if not oid or not labels_are_owner(olabels):
                continue
            oprops = {k: val for k, val in em.items() if k not in ("id", "label")}
            raw_owners.append(
                search_hit_from_node(
                    tenant_id,
                    oid,
                    olabels,
                    oprops,
                    matched_on=ident["matched_on"],
                    via={"entity_id": ident["entity_id"], "labels": ident["labels"]},
                )
            )
        raw_owners.sort(key=lambda h: str(h.get("entity_id") or ""))
        owners = cap_identifier_owners(raw_owners)
        rows = merge_search_hits(directs + owners, label=label, limit=limit)
        return rows, truncated

    return await run_in_gremlin_thread(_search_entities_sync)


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
