import json
import re
from typing import Any

import asyncpg

from .config import settings
from .custom_schema import get_allowed_labels, get_allowed_rels
from .entity_risk_score import decorate_subgraph_node, link_props_for_create, link_props_for_match
from .hetero_schema import validate_typed_edge_or_raise

_pool: asyncpg.Pool | None = None

ALLOWED_LABELS = frozenset({"Person", "Account", "Device", "Payment", "Document", "Custom"})
ALLOWED_RELS = frozenset(
    {"USED", "SHARED_WITH", "REFERRED", "KYC_VERIFIED_BY", "OWNS", "CUSTOM", "RELATED"}
)

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


async def init_pool() -> None:
    global _pool
    if _pool is None:

        async def init_connection(conn: asyncpg.Connection) -> None:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS age;")
            await conn.execute("LOAD 'age';")
            await conn.execute('SET search_path = ag_catalog, "$user", public;')
            # Ensure the graph exists
            await conn.execute(
                "SELECT create_graph('tarka') WHERE NOT EXISTS (SELECT * FROM ag_graph WHERE name = 'tarka');"
            )

        _pool = await asyncpg.create_pool(
            settings.database_url,
            init=init_connection,
            min_size=1,
            max_size=10,
        )


async def get_pool() -> asyncpg.Pool:
    if _pool is None:
        await init_pool()
    return _pool


async def close_driver() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def upsert_entity(
    tenant_id: str,
    entity_type: str,
    external_id: str,
    properties: dict[str, Any],
    tags: list[str] | None = None,
) -> str:
    pool = await get_pool()
    tenant_labels = get_allowed_labels(tenant_id)
    label = entity_type if entity_type in (ALLOWED_LABELS | tenant_labels) else "Custom"
    label = _sanitize_label(label)
    props = {**properties, "tenant_id": tenant_id, "external_id": external_id}
    if tags is not None:
        props["tags"] = tags

    # AGE does not support parameterized labels, so we inject the sanitized label
    # AGE parameterization uses a JSON map
    json.dumps(props)

    q = f"""
    SELECT CAST(CAST(gid AS VARCHAR) AS JSON) as gid FROM cypher('tarka', $$
        MERGE (n:{label} {{tenant_id: $tenant_id, external_id: $external_id}})
        SET n += $props
        RETURN id(n)
    $$, %s) as (gid agtype);
    """

    # We pass the parameters as a JSON string to the cypher function
    params_json = json.dumps({"tenant_id": tenant_id, "external_id": external_id, "props": props})

    async with pool.acquire() as conn:
        row = await conn.fetchrow(q, params_json)
        return str(json.loads(row["gid"])) if row else ""


async def update_tags(
    tenant_id: str,
    external_id: str,
    tags: list[str],
) -> list[str]:
    pool = await get_pool()
    # AGE doesn't have APOC, so we fetch existing, merge in Python, and update
    q_fetch = """
    SELECT CAST(CAST(tags AS VARCHAR) AS JSON) as tags FROM cypher('tarka', $$
        MATCH (n {tenant_id: $tenant_id, external_id: $external_id})
        RETURN n.tags
    $$, %s) as (tags agtype);
    """

    params_json = json.dumps({"tenant_id": tenant_id, "external_id": external_id})

    async with pool.acquire() as conn:
        row = await conn.fetchrow(q_fetch, params_json)
        existing_tags = []
        if row and row["tags"] and row["tags"] != "null":
            existing_tags = json.loads(row["tags"])

        merged_tags = sorted(set(existing_tags) | set(tags))

        q_update = """
        SELECT * FROM cypher('tarka', $$
            MATCH (n {tenant_id: $tenant_id, external_id: $external_id})
            SET n.tags = $tags, n.tags_updated_at = timestamp()
            RETURN n
        $$, %s) as (n agtype);
        """
        update_params = json.dumps(
            {"tenant_id": tenant_id, "external_id": external_id, "tags": merged_tags}
        )
        await conn.execute(q_update, update_params)
        return merged_tags


async def get_tags(tenant_id: str, external_id: str) -> list[str]:
    pool = await get_pool()
    q = """
    SELECT CAST(CAST(tags AS VARCHAR) AS JSON) as tags FROM cypher('tarka', $$
        MATCH (n {tenant_id: $tenant_id, external_id: $external_id})
        RETURN n.tags
    $$, %s) as (tags agtype);
    """
    params_json = json.dumps({"tenant_id": tenant_id, "external_id": external_id})
    async with pool.acquire() as conn:
        row = await conn.fetchrow(q, params_json)
        if row and row["tags"] and row["tags"] != "null":
            return json.loads(row["tags"])
    return []


async def create_link(
    tenant_id: str,
    from_external_id: str,
    to_external_id: str,
    relationship: str,
    properties: dict[str, Any],
) -> None:
    pool = await get_pool()
    rel = relationship.upper().replace(" ", "_")
    tenant_rels = get_allowed_rels(tenant_id)
    if rel not in (ALLOWED_RELS | tenant_rels):
        rel = "RELATED"
    rel = _sanitize_rel(rel)
    create_props = link_props_for_create(properties)
    match_props = link_props_for_match(properties)

    q_meta = """
    SELECT CAST(CAST(la AS VARCHAR) AS JSON) as la, CAST(CAST(lb AS VARCHAR) AS JSON) as lb FROM cypher('tarka', $$
        MATCH (a {tenant_id: $tenant_id, external_id: $from_id})
        MATCH (b {tenant_id: $tenant_id, external_id: $to_id})
        RETURN labels(a), labels(b)
    $$, %s) as (la agtype, lb agtype);
    """

    q = f"""
    SELECT * FROM cypher('tarka', $$
        MATCH (a {{tenant_id: $tenant_id, external_id: $from_id}})
        MATCH (b {{tenant_id: $tenant_id, external_id: $to_id}})
        MERGE (a)-[r:{rel}]->(b)
        ON CREATE SET r += $create_props
        ON MATCH SET r += $match_props
        RETURN r
    $$, %s) as (r agtype);
    """

    params_json = json.dumps(
        {
            "tenant_id": tenant_id,
            "from_id": from_external_id,
            "to_id": to_external_id,
            "create_props": create_props,
            "match_props": match_props,
        }
    )

    async with pool.acquire() as conn:
        row = await conn.fetchrow(q_meta, params_json)
        if row:
            la = json.loads(row["la"]) if row["la"] and row["la"] != "null" else []
            lb = json.loads(row["lb"]) if row["lb"] and row["lb"] != "null" else []
            validate_typed_edge_or_raise(tenant_id, rel, la, lb)

        await conn.execute(q, params_json)


async def list_one_hop_ids(tenant_id: str, entity_id: str) -> list[str]:
    pool = await get_pool()
    q = """
    SELECT CAST(CAST(ids AS VARCHAR) AS JSON) as ids FROM cypher('tarka', $$
        MATCH (n {tenant_id: $tenant_id, external_id: $entity_id})-[r]-(m)
        WHERE m.tenant_id = $tenant_id
        RETURN collect(DISTINCT m.external_id)
    $$, %s) as (ids agtype);
    """
    params_json = json.dumps({"tenant_id": tenant_id, "entity_id": entity_id})
    async with pool.acquire() as conn:
        row = await conn.fetchrow(q, params_json)
    if not row or not row["ids"] or row["ids"] == "null":
        return []
    raw = json.loads(row["ids"])
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw if x]


async def load_peer_p90_by_label(tenant_id: str, label: str) -> int | None:
    from .graph_runtime import parse_p90_degree_by_label

    try:
        pool = await get_pool()
        q = """
        SELECT CAST(CAST(raw AS VARCHAR) AS JSON) as raw
        FROM cypher('tarka', $$
            MATCH (s:GraphRiskStats {tenant_id: $tenant_id})
            RETURN s.p90_degree_by_label
        $$, %s) as (raw agtype);
        """
        async with pool.acquire() as conn:
            row = await conn.fetchrow(q, json.dumps({"tenant_id": tenant_id}))
        if not row or not row["raw"] or row["raw"] == "null":
            return None
        raw = json.loads(row["raw"])
        return parse_p90_degree_by_label(raw, label)
    except Exception:
        return None


async def set_entity_risk_properties(tenant_id: str, entity_id: str, props: dict[str, Any]) -> None:
    pool = await get_pool()
    q = """
    SELECT * FROM cypher('tarka', $$
        MATCH (n {tenant_id: $tenant_id, external_id: $entity_id})
        SET n.risk_score = $risk_score,
            n.risk_factors = $risk_factors,
            n.risk_computed_at = $risk_computed_at,
            n.relation_count = $relation_count,
            n.relation_growth_1h = $relation_growth_1h,
            n.relation_growth_24h = $relation_growth_24h
        RETURN n
    $$, %s) as (n agtype);
    """
    params_json = json.dumps(
        {
            "tenant_id": tenant_id,
            "entity_id": entity_id,
            "risk_score": props.get("risk_score"),
            "risk_factors": list(props.get("risk_factors") or []),
            "risk_computed_at": props.get("risk_computed_at"),
            "relation_count": props.get("relation_count"),
            "relation_growth_1h": props.get("relation_growth_1h"),
            "relation_growth_24h": props.get("relation_growth_24h"),
        }
    )
    async with pool.acquire() as conn:
        await conn.execute(q, params_json)


def _node_to_dict(n: dict[str, Any]) -> dict[str, Any]:
    return decorate_subgraph_node(
        {
            "id": str(n.get("id")),
            "labels": [n.get("label")],
            "properties": n.get("properties", {}),
        }
    )


async def query_subgraph(tenant_id: str, entity_id: str, depth: int) -> dict[str, Any]:
    pool = await get_pool()
    depth = max(1, min(int(depth), 5))

    # AGE doesn't support returning paths directly in the same way as Neo4j
    # We will fetch vertices and edges within the depth
    q = f"""
    SELECT CAST(CAST(v AS VARCHAR) AS JSON) as v, CAST(CAST(e AS VARCHAR) AS JSON) as e FROM cypher('tarka', $$
        MATCH p = (root {{tenant_id: $tenant_id, external_id: $eid}})-[*0..{depth}]-(n)
        UNWIND nodes(p) as v
        UNWIND relationships(p) as e
        RETURN DISTINCT v, e
    $$, %s) as (v agtype, e agtype);
    """

    params_json = json.dumps({"tenant_id": tenant_id, "eid": entity_id})

    nodes_out: list[dict[str, Any]] = []
    edges_out: list[dict[str, Any]] = []

    async with pool.acquire() as conn:
        rows = await conn.fetch(q, params_json)

        if not rows:
            # Check if root node exists
            q_root = """
            SELECT CAST(CAST(n AS VARCHAR) AS JSON) as n FROM cypher('tarka', $$
                MATCH (n {tenant_id: $tenant_id, external_id: $eid})
                RETURN n
            $$, %s) as (n agtype);
            """
            root_row = await conn.fetchrow(q_root, params_json)
            if root_row and root_row["n"] and root_row["n"] != "null":
                n = json.loads(root_row["n"])
                nodes_out.append(_node_to_dict(n))
        else:
            seen_nodes = set()
            seen_edges = set()
            for row in rows:
                if row["v"] and row["v"] != "null":
                    v = json.loads(row["v"])
                    vid = str(v.get("id"))
                    if vid not in seen_nodes:
                        seen_nodes.add(vid)
                        nodes_out.append(_node_to_dict(v))
                if row["e"] and row["e"] != "null":
                    e = json.loads(row["e"])
                    eid = str(e.get("id"))
                    if eid not in seen_edges:
                        seen_edges.add(eid)
                        edges_out.append(
                            {
                                "id": eid,
                                "type": e.get("label"),
                                "startNode": str(e.get("start_id")),
                                "endNode": str(e.get("end_id")),
                                "properties": e.get("properties", {}),
                            }
                        )

    return {"nodes": nodes_out, "edges": edges_out}


async def query_entity_deep_context(tenant_id: str, external_id: str) -> dict[str, Any] | None:
    from .entity_context_shape import shape_deep_context_from_nodes

    sub = await query_subgraph(tenant_id, external_id, 2)
    nodes = sub.get("nodes") or []
    if not nodes or not any(n.get("id") == external_id for n in nodes):
        return None
    return shape_deep_context_from_nodes(external_id, tenant_id, nodes)


def _age_json(val: Any) -> Any:
    if val is None or val == "null":
        return None
    if isinstance(val, (dict, list, int, float, bool)):
        return val
    try:
        return json.loads(val)
    except (TypeError, ValueError, json.JSONDecodeError):
        return val


async def list_entity_risk_top(
    tenant_id: str, limit: int = 50, min_score: float = 0
) -> list[dict[str, Any]]:
    from .entity_risk_writeback import clamp_top_limit

    limit = clamp_top_limit(limit)
    try:
        min_score = float(min_score)
    except (TypeError, ValueError):
        min_score = 0.0
    pool = await get_pool()
    q = f"""
    SELECT CAST(CAST(entity_id AS VARCHAR) AS JSON) as entity_id,
           CAST(CAST(labels AS VARCHAR) AS JSON) as labels,
           CAST(CAST(risk_score AS VARCHAR) AS JSON) as risk_score,
           CAST(CAST(risk_factors AS VARCHAR) AS JSON) as risk_factors,
           CAST(CAST(risk_computed_at AS VARCHAR) AS JSON) as risk_computed_at,
           CAST(CAST(relation_count AS VARCHAR) AS JSON) as relation_count,
           CAST(CAST(relation_growth_1h AS VARCHAR) AS JSON) as relation_growth_1h,
           CAST(CAST(relation_growth_24h AS VARCHAR) AS JSON) as relation_growth_24h
    FROM cypher('tarka', $$
        MATCH (n {{tenant_id: $tenant_id}})
        WHERE n.risk_computed_at IS NOT NULL AND n.risk_score >= $min_score
        RETURN n.external_id, labels(n), n.risk_score, n.risk_factors,
               n.risk_computed_at, n.relation_count, n.relation_growth_1h, n.relation_growth_24h
        ORDER BY n.risk_score DESC, n.external_id ASC
        LIMIT {int(limit)}
    $$, %s) as (
        entity_id agtype, labels agtype, risk_score agtype, risk_factors agtype,
        risk_computed_at agtype, relation_count agtype, relation_growth_1h agtype,
        relation_growth_24h agtype
    );
    """
    params_json = json.dumps({"tenant_id": tenant_id, "min_score": min_score})
    async with pool.acquire() as conn:
        rows = await conn.fetch(q, params_json)
    out: list[dict[str, Any]] = []
    for row in rows or []:
        labels = _age_json(row["labels"]) or []
        if not isinstance(labels, list):
            labels = [labels]
        factors = _age_json(row["risk_factors"]) or []
        if not isinstance(factors, list):
            factors = [factors] if factors else []
        eid = _age_json(row["entity_id"])
        out.append(
            {
                "entity_id": str(eid or ""),
                "labels": [str(x) for x in labels],
                "risk_score": float(_age_json(row["risk_score"]) or 0),
                "risk_factors": [str(x) for x in factors],
                "risk_computed_at": _age_json(row["risk_computed_at"]),
                "relation_count": int(_age_json(row["relation_count"]) or 0),
                "relation_growth_1h": int(_age_json(row["relation_growth_1h"]) or 0),
                "relation_growth_24h": int(_age_json(row["relation_growth_24h"]) or 0),
            }
        )
    return out


async def scan_tenant_entity_ids(tenant_id: str, limit: int) -> tuple[list[str], bool]:
    from .entity_risk_writeback import clamp_refresh_limit

    limit = clamp_refresh_limit(limit)
    fetch = int(limit) + 1
    pool = await get_pool()
    q = f"""
    SELECT CAST(CAST(entity_id AS VARCHAR) AS JSON) as entity_id
    FROM cypher('tarka', $$
        MATCH (n {{tenant_id: $tenant_id}})
        WHERE n.external_id IS NOT NULL
        RETURN n.external_id
        ORDER BY n.external_id ASC
        LIMIT {fetch}
    $$, %s) as (entity_id agtype);
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(q, json.dumps({"tenant_id": tenant_id}))
    ids: list[str] = []
    for row in rows or []:
        eid = _age_json(row["entity_id"])
        if eid:
            ids.append(str(eid))
    truncated = len(ids) > limit
    return ids[:limit], truncated


async def upsert_graph_risk_stats(
    tenant_id: str, p90_degree_by_label: dict[str, int], stats_computed_at: str
) -> None:
    pool = await get_pool()
    q = """
    SELECT * FROM cypher('tarka', $$
        MERGE (s:GraphRiskStats {tenant_id: $tenant_id})
        SET s.p90_degree_by_label = $p90_json,
            s.stats_computed_at = $stats_computed_at
        RETURN s
    $$, %s) as (s agtype);
    """
    params_json = json.dumps(
        {
            "tenant_id": tenant_id,
            "p90_json": json.dumps(p90_degree_by_label or {}),
            "stats_computed_at": stats_computed_at,
        }
    )
    async with pool.acquire() as conn:
        await conn.execute(q, params_json)
