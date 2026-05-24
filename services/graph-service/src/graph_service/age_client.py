import json
import re
from typing import Any

import asyncpg

from graph_service.config import settings
from graph_service.custom_schema import get_allowed_labels, get_allowed_rels
from graph_service.hetero_schema import validate_typed_edge_or_raise

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
    props_json = json.dumps(props)

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
        SET r += $rel_props
        RETURN r
    $$, %s) as (r agtype);
    """

    params_json = json.dumps(
        {
            "tenant_id": tenant_id,
            "from_id": from_external_id,
            "to_id": to_external_id,
            "rel_props": properties or {},
        }
    )

    async with pool.acquire() as conn:
        row = await conn.fetchrow(q_meta, params_json)
        if row:
            la = json.loads(row["la"]) if row["la"] and row["la"] != "null" else []
            lb = json.loads(row["lb"]) if row["lb"] and row["lb"] != "null" else []
            validate_typed_edge_or_raise(tenant_id, rel, la, lb)

        await conn.execute(q, params_json)


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
                nodes_out.append(
                    {
                        "id": str(n.get("id")),
                        "labels": [n.get("label")],
                        "properties": n.get("properties", {}),
                    }
                )
        else:
            seen_nodes = set()
            seen_edges = set()
            for row in rows:
                if row["v"] and row["v"] != "null":
                    v = json.loads(row["v"])
                    vid = str(v.get("id"))
                    if vid not in seen_nodes:
                        seen_nodes.add(vid)
                        nodes_out.append(
                            {
                                "id": vid,
                                "labels": [v.get("label")],
                                "properties": v.get("properties", {}),
                            }
                        )
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
