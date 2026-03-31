from typing import Any

from neo4j import AsyncGraphDatabase, AsyncDriver

from graph_service.config import settings
from graph_service.custom_schema import get_allowed_labels, get_allowed_rels

_driver: AsyncDriver | None = None

ALLOWED_LABELS = frozenset({"Person", "Account", "Device", "Payment", "Document", "Custom"})
ALLOWED_RELS = frozenset({"USED", "SHARED_WITH", "REFERRED", "KYC_VERIFIED_BY", "OWNS", "CUSTOM", "RELATED"})

import re
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")

def _sanitize_label(label: str) -> str:
    """Reject labels that could contain Cypher injection."""
    if not _SAFE_IDENTIFIER.match(label):
        return "Custom"
    return label

def _sanitize_rel(rel: str) -> str:
    if not _SAFE_IDENTIFIER.match(rel):
        return "RELATED"
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
    tenant_labels = get_allowed_labels(tenant_id)
    label = entity_type if entity_type in (ALLOWED_LABELS | tenant_labels) else "Custom"
    label = _sanitize_label(label)
    props = {**properties, "tenant_id": tenant_id, "external_id": external_id}
    if tags is not None:
        props["tags"] = tags

    q = f"""
    MERGE (n:{label} {{tenant_id: $tenant_id, external_id: $external_id}})
    SET n += $properties
    RETURN elementId(n) AS gid
    """
    async with driver.session() as session:
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
            result = await session.run(q, tenant_id=tenant_id, external_id=external_id, new_tags=tags)
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
                tenant_id=tenant_id, external_id=external_id, tags=merged,
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
    rel = relationship.upper().replace(" ", "_")
    tenant_rels = get_allowed_rels(tenant_id)
    if rel not in (ALLOWED_RELS | tenant_rels):
        rel = "RELATED"
    rel = _sanitize_rel(rel)
    q = f"""
    MATCH (a {{tenant_id: $tenant_id, external_id: $from_id}})
    MATCH (b {{tenant_id: $tenant_id, external_id: $to_id}})
    MERGE (a)-[r:{rel}]->(b)
    SET r += $rel_props
    """
    async with driver.session() as session:
        await session.run(
            q,
            tenant_id=tenant_id,
            from_id=from_external_id,
            to_id=to_external_id,
            rel_props=properties or {},
        )


async def query_subgraph(tenant_id: str, entity_id: str, depth: int) -> dict[str, Any]:
    driver = await get_driver()
    depth = max(1, min(int(depth), 5))
    q = f"""
    MATCH (root {{tenant_id: $tenant_id, external_id: $eid}})
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
                t=tenant_id, e=entity_id,
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
    return {"id": eid or str(props.get("element_id", "")), "labels": labels, "properties": props}


def _rel_to_dict(r: Any) -> dict[str, Any]:
    sn, en = r.start_node, r.end_node
    return {
        "from_id": dict(sn).get("external_id", ""),
        "to_id": dict(en).get("external_id", ""),
        "type": r.type,
        "properties": dict(r),
    }
