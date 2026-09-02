import re
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase

from .config import settings
from .custom_schema import get_allowed_labels, get_allowed_rels
from .entity_context_shape import shape_deep_context_from_nodes
from .entity_risk_score import (
    _link_properties_with_observed_at,
    decorate_subgraph_node,
    link_props_for_match,
)
from .hetero_schema import validate_typed_edge_or_raise
from graph_contract import (
    UnsignedGraphToken,
    merge_roles,
    require_etype,
    require_vtype,
    roles_from_properties,
)

_driver: AsyncDriver | None = None

ALLOWED_LABELS = frozenset(
    {
        "user",
        "device",
        "ip",
        "phone",
        "payment",
        "place",
        "promo",
        "order",
        "Person",
        "Account",
        "Device",
        "Payment",
        "Login",
        "Session",
        "Ip",
        "Document",
        "LicensePlate",
        "Decision",
        "Email",
        "Phone",
        "Place",
        "Address",
        "Card",
        "List",
        "Custom",
    }
)
ALLOWED_RELS = frozenset(
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
        "USES_DEVICE",
        "HAS_EMAIL",
        "HAS_PHONE",
        "HAS_CARD",
        "HAS_LIST",
        "SEEN_FROM_IP",
        "PAYS_WITH",
        "RESULTED_IN",
        "ACTED_ON",
        "BASED_ON",
        "SUPERSEDES",
        "SHARED_WITH",
        "CUSTOM",
    }
)

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


def _sanitize_label(label: str) -> str:
    """Reject labels that could contain Cypher injection."""
    if not _SAFE_IDENTIFIER.match(label):
        raise UnsignedGraphToken("vtype", label)
    return label


def _sanitize_rel(rel: str) -> str:
    if not _SAFE_IDENTIFIER.match(rel):
        raise UnsignedGraphToken("etype", rel)
    return rel


async def get_driver() -> AsyncDriver:
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
    return _driver


async def close_driver() -> None:
    global _driver
    if _driver:
        await _driver.close()
        _driver = None


async def upsert_entity(
    tenant_id: str,
    entity_type: str,
    external_id: str,
    properties: dict[str, Any],
    tags: list[str] | None = None,
) -> str:
    driver = await get_driver()
    get_allowed_labels(tenant_id)
    label = require_vtype(tenant_id, entity_type)
    label = _sanitize_label(label)
    props = {**properties, "tenant_id": tenant_id, "external_id": external_id, "vtype": label}
    if tags is not None:
        props["tags"] = tags
    incoming_roles = roles_from_properties(properties)

    q_exist = f"""
    MATCH (n:{label} {{tenant_id: $tenant_id, external_id: $external_id}})
    RETURN n.roles AS roles LIMIT 1
    """
    q = f"""
    MERGE (n:{label} {{tenant_id: $tenant_id, external_id: $external_id}})
    SET n += $properties, n.updated_at = datetime()
    RETURN elementId(n) AS gid
    """
    async with driver.session() as session:
        existing = await session.run(q_exist, tenant_id=tenant_id, external_id=external_id)
        erec = await existing.single()
        old_roles = list(erec["roles"] or []) if erec and erec["roles"] else []
        props["roles"] = merge_roles(old_roles, incoming_roles)
        result = await session.run(
            q,
            tenant_id=tenant_id,
            external_id=external_id,
            properties=props,
        )
        rec = await result.single()
        return str(rec["gid"]) if rec else ""


async def update_tags(
    tenant_id: str,
    external_id: str,
    tags: list[str],
) -> list[str]:
    driver = await get_driver()
    q = """
    MATCH (n {tenant_id: $tenant_id, external_id: $external_id})
    WITH n, CASE WHEN n.tags IS NULL THEN [] ELSE n.tags END AS existing
    WITH n, [t IN (existing + $new_tags) | t] AS all_tags
    WITH n, apoc.coll.toSet(all_tags) AS unique_tags
    SET n.tags = unique_tags, n.tags_updated_at = datetime()
    RETURN n.tags AS tags
    """
    # Fallback without APOC
    q_fallback = """
    MATCH (n {tenant_id: $tenant_id, external_id: $external_id})
    RETURN n.tags AS tags
    """
    async with driver.session() as session:
        try:
            result = await session.run(
                q, tenant_id=tenant_id, external_id=external_id, new_tags=tags
            )
            rec = await result.single()
            if rec:
                return list(rec["tags"] or [])
        except Exception:
            # APOC not available, do read-modify-write
            result = await session.run(q_fallback, tenant_id=tenant_id, external_id=external_id)
            rec = await result.single()
            existing = list(rec["tags"] or []) if rec and rec["tags"] else []
            merged = sorted(set(existing) | set(tags))
            await session.run(
                """
                MATCH (n {tenant_id: $tenant_id, external_id: $external_id})
                SET n.tags = $tags, n.tags_updated_at = datetime()
                """,
                tenant_id=tenant_id,
                external_id=external_id,
                tags=merged,
            )
            return merged
    return tags


async def get_tags(tenant_id: str, external_id: str) -> list[str]:
    driver = await get_driver()
    q = "MATCH (n {tenant_id: $t, external_id: $e}) RETURN n.tags AS tags LIMIT 1"
    async with driver.session() as session:
        result = await session.run(q, t=tenant_id, e=external_id)
        rec = await result.single()
        if rec and rec["tags"]:
            return list(rec["tags"])
    return []


async def create_link(
    tenant_id: str,
    from_external_id: str,
    to_external_id: str,
    relationship: str,
    properties: dict[str, Any],
) -> None:
    driver = await get_driver()
    get_allowed_rels(tenant_id)
    rel = require_etype(tenant_id, relationship)
    rel = _sanitize_rel(rel)
    from_vtype = (properties or {}).get("from_vtype") or (properties or {}).get("from_entity_type")
    to_vtype = (properties or {}).get("to_vtype") or (properties or {}).get("to_entity_type")

    def _endpoint(alias: str, id_param: str, vtype: Any) -> str:
        if vtype:
            lab = _sanitize_label(require_vtype(tenant_id, str(vtype)))
            return f"({alias}:{lab} {{tenant_id: $tenant_id, external_id: ${id_param}}})"
        return f"({alias} {{tenant_id: $tenant_id, external_id: ${id_param}}})"

    a_pat = _endpoint("a", "from_id", from_vtype)
    b_pat = _endpoint("b", "to_id", to_vtype)
    edge_props = {
        k: v
        for k, v in (properties or {}).items()
        if k not in ("from_vtype", "to_vtype", "from_entity_type", "to_entity_type")
    }
    create_props = _link_properties_with_observed_at(edge_props)
    match_props = link_props_for_match(edge_props)
    q_meta = f"""
    MATCH {a_pat}
    MATCH {b_pat}
    RETURN labels(a) AS la, labels(b) AS lb
    """
    q = f"""
    MATCH {a_pat}
    MATCH {b_pat}
    MERGE (a)-[r:{rel}]->(b)
    ON CREATE SET r += $create_props
    ON MATCH SET r += $match_props
    """
    async with driver.session() as session:
        meta = await session.run(
            q_meta,
            tenant_id=tenant_id,
            from_id=from_external_id,
            to_id=to_external_id,
        )
        mrec = await meta.single()
        if mrec:
            validate_typed_edge_or_raise(
                tenant_id, rel, list(mrec["la"] or []), list(mrec["lb"] or [])
            )
        await session.run(
            q,
            tenant_id=tenant_id,
            from_id=from_external_id,
            to_id=to_external_id,
            create_props=create_props,
            match_props=match_props,
        )


async def delete_entity(tenant_id: str, external_id: str) -> None:
    driver = await get_driver()
    q = """
    MATCH (n {tenant_id: $tenant_id, external_id: $external_id})
    DETACH DELETE n
    """
    async with driver.session() as session:
        await session.run(q, tenant_id=tenant_id, external_id=external_id)


async def list_one_hop_ids(tenant_id: str, entity_id: str) -> list[str]:
    driver = await get_driver()
    q = """
    MATCH (n {tenant_id: $tenant_id, external_id: $entity_id})-[r]-(m)
    WHERE m.tenant_id = $tenant_id
    RETURN collect(DISTINCT m.external_id) AS ids
    """
    async with driver.session() as session:
        result = await session.run(q, tenant_id=tenant_id, entity_id=entity_id)
        rec = await result.single()
        if not rec or rec["ids"] is None:
            return []
        return [str(x) for x in rec["ids"] if x]


async def query_subgraph(tenant_id: str, entity_id: str, depth: int) -> dict[str, Any]:
    driver = await get_driver()
    depth = max(1, min(int(depth), 5))
    q = f"""
    OPTIONAL MATCH (u:user {{tenant_id: $tenant_id, external_id: $eid}})
    WITH u
    OPTIONAL MATCH (x {{tenant_id: $tenant_id, external_id: $eid}})
    WHERE u IS NULL
    WITH u, collect(DISTINCT x) AS hits
    WITH coalesce(u, CASE WHEN size(hits) = 1 THEN hits[0] ELSE null END) AS root
    WHERE root IS NOT NULL
    OPTIONAL MATCH p = (root)-[*1..{depth}]-(n)
    WITH collect(DISTINCT root) + collect(DISTINCT n) AS node_list, collect(p) AS paths
    WITH node_list,
         reduce(acc = [], path IN [x IN paths WHERE x IS NOT NULL] | acc + relationships(path)) AS all_rels
    RETURN node_list, all_rels
    """
    nodes_out: list[dict[str, Any]] = []
    edges_out: list[dict[str, Any]] = []
    async with driver.session() as session:
        result = await session.run(q, tenant_id=tenant_id, eid=entity_id)
        rec = await result.single()

    if not rec:
        async with driver.session() as session:
            result = await session.run(
                "MATCH (n {tenant_id: $t, external_id: $e}) RETURN n LIMIT 1",
                t=tenant_id,
                e=entity_id,
            )
            nrec = await result.single()
            if nrec:
                nodes_out.append(_node_to_dict(nrec["n"]))
        return {"nodes": nodes_out, "edges": edges_out}

    seen_n: set[str] = set()
    for n in rec["node_list"] or []:
        if n is None:
            continue
        eid = dict(n).get("external_id", "")
        if eid in seen_n:
            continue
        seen_n.add(eid)
        nodes_out.append(_node_to_dict(n))
    seen_r: set[str] = set()
    for rel in rec["all_rels"] or []:
        if rel is None:
            continue
        rkey = f"{dict(rel.start_node).get('external_id', '')}_{rel.type}_{dict(rel.end_node).get('external_id', '')}"
        if rkey in seen_r:
            continue
        seen_r.add(rkey)
        edges_out.append(_rel_to_dict(rel))
    return {"nodes": nodes_out, "edges": edges_out}


def _node_to_dict(n: Any) -> dict[str, Any]:
    labels = list(n.labels) if hasattr(n, "labels") else []
    props = dict(n)
    eid = props.get("external_id", "")
    return decorate_subgraph_node(
        {"id": eid or str(props.get("element_id", "")), "labels": labels, "properties": props}
    )


def _rel_to_dict(r: Any) -> dict[str, Any]:
    sn, en = r.start_node, r.end_node
    return {
        "from_id": dict(sn).get("external_id", ""),
        "to_id": dict(en).get("external_id", ""),
        "type": r.type,
        "properties": dict(r),
    }


async def set_entity_risk_properties(tenant_id: str, entity_id: str, props: dict[str, Any]) -> None:
    driver = await get_driver()
    q = """
    MATCH (n {tenant_id: $tenant_id, external_id: $entity_id})
    SET n.risk_score = $risk_score,
        n.risk_factors = $risk_factors,
        n.risk_computed_at = $risk_computed_at,
        n.relation_count = $relation_count,
        n.relation_growth_1h = $relation_growth_1h,
        n.relation_growth_24h = $relation_growth_24h
    """
    async with driver.session() as session:
        await session.run(
            q,
            tenant_id=tenant_id,
            entity_id=entity_id,
            risk_score=props.get("risk_score"),
            risk_factors=list(props.get("risk_factors") or []),
            risk_computed_at=props.get("risk_computed_at"),
            relation_count=props.get("relation_count"),
            relation_growth_1h=props.get("relation_growth_1h"),
            relation_growth_24h=props.get("relation_growth_24h"),
        )


def _entity_risk_top_row(rec: Any) -> dict[str, Any]:
    labels = rec.get("labels") or []
    if not isinstance(labels, list):
        labels = list(labels)
    factors = rec.get("risk_factors") or []
    if not isinstance(factors, list):
        factors = list(factors) if factors else []
    return {
        "entity_id": str(rec.get("entity_id") or ""),
        "labels": [str(x) for x in labels],
        "risk_score": float(rec.get("risk_score") or 0),
        "risk_factors": [str(x) for x in factors],
        "risk_computed_at": rec.get("risk_computed_at"),
        "relation_count": int(rec.get("relation_count") or 0),
        "relation_growth_1h": int(rec.get("relation_growth_1h") or 0),
        "relation_growth_24h": int(rec.get("relation_growth_24h") or 0),
    }


async def search_entities(
    tenant_id: str, q: str, label: str | None = None, limit: int = 20
) -> tuple[list[dict[str, Any]], bool]:
    from .entity_risk_score import (
        OWNER_LABELS,
        cap_identifier_owners,
        clamp_search_limit,
        cypher_search_prop_predicate,
        eligible_search_node,
        labels_are_identifier,
        labels_are_owner,
        merge_search_hits,
        search_hit_from_node,
    )

    limit = clamp_search_limit(limit)
    pred = cypher_search_prop_predicate("n")
    driver = await get_driver()
    match_cypher = f"""
    MATCH (n {{tenant_id: $tenant_id}})
    WHERE NOT n:GraphRiskStats
      AND n.external_id IS NOT NULL AND n.external_id <> ''
      AND $q <> ''
      AND ({pred})
    RETURN n.external_id AS entity_id,
           labels(n) AS labels,
           properties(n) AS props
    """
    async with driver.session() as session:
        result = await session.run(match_cypher, tenant_id=tenant_id, q=q)
        rows = await result.data()
    directs: list[dict[str, Any]] = []
    ident_ids: list[str] = []
    ident_meta: dict[str, dict[str, Any]] = {}
    for rec in rows or []:
        if not rec:
            continue
        eid = str(rec.get("entity_id") or "").strip()
        labs = rec.get("labels") or []
        if not isinstance(labs, list):
            labs = list(labs)
        props = rec.get("props") or {}
        if not isinstance(props, dict):
            props = dict(props)
        matched = eligible_search_node(eid, props, q)
        if not matched:
            continue
        hit = search_hit_from_node(tenant_id, eid, labs, props, matched_on=matched, via=None)
        directs.append(hit)
        if labels_are_identifier(labs):
            ident_ids.append(eid)
            ident_meta[eid] = hit
    owners: list[dict[str, Any]] = []
    if ident_ids:
        owner_cypher = """
        MATCH (n {tenant_id: $tenant_id})--(m)
        WHERE n.external_id IN $ids
          AND NOT m:GraphRiskStats
          AND m.external_id IS NOT NULL AND m.external_id <> ''
          AND any(l IN labels(m) WHERE l IN $owner_labels)
        RETURN n.external_id AS via_id,
               m.external_id AS entity_id,
               labels(m) AS labels,
               properties(m) AS props
        ORDER BY m.external_id ASC
        """
        async with driver.session() as session:
            result = await session.run(
                owner_cypher,
                tenant_id=tenant_id,
                ids=ident_ids,
                owner_labels=list(OWNER_LABELS),
            )
            orows = await result.data()
        raw_owners: list[dict[str, Any]] = []
        for rec in orows or []:
            if not rec:
                continue
            ident = ident_meta.get(str(rec.get("via_id") or ""))
            if not ident:
                continue
            eid = str(rec.get("entity_id") or "").strip()
            labs = rec.get("labels") or []
            if not isinstance(labs, list):
                labs = list(labs)
            if not eid or not labels_are_owner(labs):
                continue
            props = rec.get("props") or {}
            if not isinstance(props, dict):
                props = dict(props)
            raw_owners.append(
                search_hit_from_node(
                    tenant_id,
                    eid,
                    labs,
                    props,
                    matched_on=ident["matched_on"],
                    via={"entity_id": ident["entity_id"], "labels": ident["labels"]},
                )
            )
        owners = cap_identifier_owners(raw_owners)
    return merge_search_hits(directs + owners, label=label, limit=limit), False


async def list_entity_risk_top(
    tenant_id: str, limit: int = 50, min_score: float = 0
) -> list[dict[str, Any]]:
    from .entity_risk_writeback import clamp_top_limit

    limit = clamp_top_limit(limit)
    try:
        min_score = float(min_score)
    except (TypeError, ValueError):
        min_score = 0.0
    driver = await get_driver()
    q = """
    MATCH (n {tenant_id: $tenant_id})
    WHERE n.risk_computed_at IS NOT NULL AND n.risk_score >= $min_score
    RETURN n.external_id AS entity_id,
           labels(n) AS labels,
           n.risk_score AS risk_score,
           n.risk_factors AS risk_factors,
           n.risk_computed_at AS risk_computed_at,
           n.relation_count AS relation_count,
           n.relation_growth_1h AS relation_growth_1h,
           n.relation_growth_24h AS relation_growth_24h
    ORDER BY n.risk_score DESC, n.external_id ASC
    LIMIT $limit
    """
    async with driver.session() as session:
        result = await session.run(q, tenant_id=tenant_id, min_score=min_score, limit=limit)
        rows = await result.data()
    return [_entity_risk_top_row(r) for r in (rows or []) if r]


async def scan_tenant_entity_ids(tenant_id: str, limit: int) -> tuple[list[str], bool]:
    from .entity_risk_writeback import clamp_refresh_limit

    limit = clamp_refresh_limit(limit)
    fetch = limit + 1
    driver = await get_driver()
    q = """
    MATCH (n {tenant_id: $tenant_id})
    WHERE n.external_id IS NOT NULL AND NOT n:GraphRiskStats
    RETURN n.external_id AS entity_id
    ORDER BY n.external_id ASC
    LIMIT $fetch
    """
    async with driver.session() as session:
        result = await session.run(q, tenant_id=tenant_id, fetch=fetch)
        rows = await result.data()
    ids = [str(r["entity_id"]) for r in (rows or []) if r and r.get("entity_id")]
    truncated = len(ids) > limit
    return ids[:limit], truncated


async def upsert_graph_risk_stats(
    tenant_id: str, p90_degree_by_label: dict[str, int], stats_computed_at: str
) -> None:
    import json

    driver = await get_driver()
    q = """
    MERGE (s:GraphRiskStats {tenant_id: $tenant_id})
    SET s.p90_degree_by_label = $p90_json,
        s.stats_computed_at = $stats_computed_at
    """
    async with driver.session() as session:
        await session.run(
            q,
            tenant_id=tenant_id,
            p90_json=json.dumps(p90_degree_by_label or {}),
            stats_computed_at=stats_computed_at,
        )


async def load_peer_p90_by_label(tenant_id: str, label: str) -> int | None:
    from .graph_runtime import parse_p90_degree_by_label

    try:
        driver = await get_driver()
        q = """
        MATCH (s:GraphRiskStats {tenant_id: $tenant_id})
        RETURN s.p90_degree_by_label AS raw
        """
        async with driver.session() as session:
            result = await session.run(q, tenant_id=tenant_id)
            rec = await result.single()
        if rec is None:
            return None
        raw = rec.get("raw") if hasattr(rec, "get") else rec["raw"]
        return parse_p90_degree_by_label(raw, label)
    except Exception:
        return None


async def query_entity_deep_context(tenant_id: str, external_id: str) -> dict[str, Any] | None:
    """Reuse bounded subgraph expansion; ``None`` when the entity is not in the graph."""
    sub = await query_subgraph(tenant_id, external_id, 2)
    nodes = sub.get("nodes") or []
    if not nodes or not any(n.get("id") == external_id for n in nodes):
        return None
    return shape_deep_context_from_nodes(external_id, tenant_id, nodes)
