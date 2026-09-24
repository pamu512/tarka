import json
import re
from contextlib import asynccontextmanager, suppress
from typing import Any, AsyncIterator

import asyncpg

from .config import settings
from .custom_schema import get_allowed_labels, get_allowed_rels
from .graph_runtime import merge_stored_trace_ids
import logging
from datetime import UTC, datetime

from .entity_risk_score import is_found_payload
from .hunt_depth import HUNT_DEPTH_MAX

log = logging.getLogger("graph_service.age_client")
from .entity_risk_score import (
    decorate_subgraph_node,
    link_props_for_create,
    link_props_for_match,
)
from .hetero_schema import validate_typed_edge_or_raise
from graph_contract import UnsignedGraphToken, require_etype, require_vtype

_pool: asyncpg.Pool | None = None

# Hop v1.2 core + Hunt write labels. Tenant schema may add more.
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


def _cypher_set_assignments(
    alias: str, values: dict[str, Any], *, prefix: str
) -> tuple[str, dict[str, Any]]:
    """AGE SET n += $map rejects nested param maps; assign sanitized keys one by one."""
    parts: list[str] = []
    params: dict[str, Any] = {}
    for key, val in values.items():
        if val is None or not _SAFE_IDENTIFIER.match(str(key)):
            continue
        pname = f"{prefix}_{key}"
        if not _SAFE_IDENTIFIER.match(pname):
            continue
        parts.append(f"{alias}.{key} = ${pname}")
        params[pname] = val
    return ", ".join(parts), params


def _cypher_lit(val: Any) -> str:
    """Literal for 2-arg cypher(). AGE 1.6 param WHERE/$eq is unreliable via asyncpg."""
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, int) and not isinstance(val, bool):
        return str(val)
    if isinstance(val, float):
        return repr(val)
    if isinstance(val, (list, dict)):
        return json.dumps(val)
    return json.dumps(str(val))


_EDGE_INDEXES_ENSURED = False

_SAFE_AGE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quote_age_ident(name: str) -> str:
    """Quote an AGE label identifier for DDL; refuse anything unexpected."""
    if not _SAFE_AGE_IDENT.match(name or ""):
        raise ValueError(f"unsafe AGE label identifier: {name!r}")
    return f'"{name}"'


def _vertex_prop_expr(prop: str) -> str:
    """AGE vertex property access expression (index-safe, 1.6 form)."""
    lit = '"' + prop + '"'
    return (
        "ag_catalog.agtype_access_operator("
        "VARIADIC ARRAY[properties, ag_catalog.agtype_in("
        f"'{lit}')])"
    )


def _vertex_tenant_index_sql(graph_name: str, label: str) -> str:
    expr = _vertex_prop_expr("tenant_id")
    return (
        f'CREATE INDEX IF NOT EXISTS ix_{label.lower()}_tenant ON {graph_name}."{label}" ({expr})'
    )


def _vertex_composite_index_sql(graph_name: str, label: str) -> str:
    tenant = _vertex_prop_expr("tenant_id")
    ext = _vertex_prop_expr("external_id")
    return (
        f"CREATE INDEX IF NOT EXISTS ix_{label.lower()}_tenant_ext "
        f'ON {graph_name}."{label}" ({tenant}, {ext})'
    )


async def ensure_age_edge_indexes(graph_name: str = "tarka") -> None:
    """Create start_id/end_id btree indexes on every AGE edge-label table.

    AGE builds per-label edge tables with only a primary key; without join
    indexes every (n)-[r]-(nb) walk plans as a nested-loop cross product
    (measured on the lite stack: 7.2M join-filter rows removed, 12-36s per
    entity-risk compute at 7.5k nodes). Two btree indexes per label restore
    index joins (measured: same query 15ms). Fail-soft: AGE unavailable or
    permission denied logs and skips — reads stay correct, just slow.
    """
    global _EDGE_INDEXES_ENSURED
    if _EDGE_INDEXES_ENSURED:
        return
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            graph_oid_row = await conn.fetchrow(
                "SELECT graphid AS graph FROM ag_catalog.ag_graph WHERE name = $1::name",
                graph_name,
            )
            graph_oid = graph_oid_row["graph"] if graph_oid_row else None
            if graph_oid is None:
                log.warning("age graph %r not found; edge indexes skipped", graph_name)
                return
            rows = await conn.fetch(
                "SELECT name FROM ag_catalog.ag_label WHERE kind = 'e' AND graph = $1::oid",
                graph_oid,
            )
            for row in rows or []:
                label = str(row["name"])
                ident = _quote_age_ident(label)
                await conn.execute(
                    f"CREATE INDEX IF NOT EXISTS ix_{label.lower()}_start "
                    f"ON {graph_name}.{ident} (start_id)"
                )
                await conn.execute(
                    f"CREATE INDEX IF NOT EXISTS ix_{label.lower()}_end "
                    f"ON {graph_name}.{ident} (end_id)"
                )
            # Vertex property indexes (same fail-soft posture): tenant_id on
            # every vertex label table; composite (tenant_id, external_id) on
            # the entity-bearing labels. Anchored lookups (entity-risk compute,
            # search hydration) went 4.5ms seq scan -> 0.04ms index scan
            # (lite-stack measured); unanchored WHERE probes skip whole-table
            # scans on large labels (Decision/Payment measured 24-33ms -> <1ms).
            vertex_rows = await conn.fetch(
                "SELECT name FROM ag_catalog.ag_label WHERE kind = 'v' AND graph = $1::oid",
                graph_oid,
            )
            for row in vertex_rows or []:
                label = str(row["name"])
                try:
                    await conn.execute(_vertex_tenant_index_sql(graph_name, label))
                    await conn.execute(_vertex_composite_index_sql(graph_name, label))
                except Exception as exc:  # noqa: BLE001
                    log.warning("vertex property index skipped label=%s: %s", label, exc)
        _EDGE_INDEXES_ENSURED = True
        log.info(
            "age indexes ensured: %d edge labels, %d vertex labels",
            len(rows or []),
            len(vertex_rows or []),
        )
    except Exception:
        log.warning("age edge index ensure skipped (fail-soft)", exc_info=True)


def _cypher_sql(body: str, columns: str, select: str = "*") -> str:
    return f"""
    SELECT {select}
    FROM ag_catalog.cypher('tarka'::name, $$
        {body}
    $$::cstring) as ({columns});
    """


def _set_literals(alias: str, values: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, val in values.items():
        if val is None or not _SAFE_IDENTIFIER.match(str(key)):
            continue
        parts.append(f"{alias}.{key} = {_cypher_lit(val)}")
    return ", ".join(parts)


async def _load_age(conn: asyncpg.Connection) -> None:
    await conn.execute("LOAD 'age';")
    await conn.execute('SET search_path = ag_catalog, "$user", public;')


async def _init_age_connection(conn: asyncpg.Connection) -> None:
    await conn.execute("CREATE EXTENSION IF NOT EXISTS age;")
    await _load_age(conn)
    exists = await conn.fetchval("SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'tarka'")
    if not exists:
        await conn.execute("SELECT create_graph('tarka');")


async def _reset_age_connection(conn: asyncpg.Connection) -> None:
    # ponytail: default RESET ALL unloads AGE; the next checkout then 500s on cypher().
    await conn.execute(conn.get_reset_query())
    await _load_age(conn)


async def init_pool() -> None:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            settings.database_url,
            init=_init_age_connection,
            reset=_reset_age_connection,
            min_size=1,
            max_size=10,
        )


async def get_pool() -> asyncpg.Pool:
    if _pool is None:
        await init_pool()
    return _pool


@asynccontextmanager
async def _acquire() -> AsyncIterator[asyncpg.Connection]:
    """Checkout a connection and ROLLBACK after a failed query so the pool stays usable."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            yield conn
        except Exception:
            with suppress(Exception):
                await conn.execute("ROLLBACK")
            raise


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
    get_allowed_labels(tenant_id)
    label = require_vtype(tenant_id, entity_type)
    label = _sanitize_label(label)
    props = {**properties, "tenant_id": tenant_id, "external_id": external_id}
    if tags is not None:
        props["tags"] = tags

    incoming_traces = properties.get("trace_ids")
    tid = _cypher_lit(tenant_id)
    eid = _cypher_lit(external_id)
    async with _acquire() as conn:
        if incoming_traces is not None:
            q_tr = _cypher_sql(
                f"MATCH (n) WHERE n.tenant_id = {tid} AND n.external_id = {eid} RETURN n.trace_ids",
                "tids ag_catalog.agtype",
                "CAST(tids AS VARCHAR) as tids",
            )
            tr_row = await conn.fetchrow(q_tr)
            existing_traces = None
            if tr_row and tr_row["tids"] and tr_row["tids"] != "null":
                existing_traces = _parse_age_graph_value(tr_row["tids"])
            props["trace_ids"] = merge_stored_trace_ids(existing_traces, incoming_traces)
        set_sql = _set_literals("n", props) or f"n.external_id = {eid}"
        q_match = _cypher_sql(
            f"MATCH (n) WHERE n.tenant_id = {tid} AND n.external_id = {eid} SET {set_sql} RETURN id(n)",
            "gid ag_catalog.agtype",
            "CAST(gid AS VARCHAR) as gid",
        )
        row = await conn.fetchrow(q_match)
        if not row or not row["gid"] or row["gid"] == "null":
            q_create = _cypher_sql(
                f"CREATE (n:{label}) SET {set_sql} RETURN id(n)",
                "gid ag_catalog.agtype",
                "CAST(gid AS VARCHAR) as gid",
            )
            row = await conn.fetchrow(q_create)
        raw = _parse_age_graph_value(row["gid"]) if row else None
        return str(raw) if raw is not None else ""


async def update_tags(
    tenant_id: str,
    external_id: str,
    tags: list[str],
) -> list[str]:
    # AGE doesn't have APOC, so we fetch existing, merge in Python, and update
    q_fetch = """
    SELECT CAST(CAST(tags AS VARCHAR) AS JSON) as tags FROM ag_catalog.cypher('tarka'::name, $$
        MATCH (n) WHERE n.tenant_id = $tenant_id AND n.external_id = $external_id
        RETURN n.tags
    $$::cstring, $1::ag_catalog.agtype) as (tags ag_catalog.agtype);
    """

    params_json = json.dumps({"tenant_id": tenant_id, "external_id": external_id})

    async with _acquire() as conn:
        row = await conn.fetchrow(q_fetch, params_json)
        existing_tags = []
        if row and row["tags"] and row["tags"] != "null":
            existing_tags = json.loads(row["tags"])

        merged_tags = sorted(set(existing_tags) | set(tags))

        q_update = """
        SELECT * FROM ag_catalog.cypher('tarka'::name, $$
            MATCH (n) WHERE n.tenant_id = $tenant_id AND n.external_id = $external_id
            SET n.tags = $tags, n.tags_updated_at = timestamp()
            RETURN n
        $$::cstring, $1::ag_catalog.agtype) as (n ag_catalog.agtype);
        """
        update_params = json.dumps(
            {"tenant_id": tenant_id, "external_id": external_id, "tags": merged_tags}
        )
        await conn.execute(q_update, update_params)
        return merged_tags


async def get_tags(tenant_id: str, external_id: str) -> list[str]:
    pool = await get_pool()
    q = """
    SELECT CAST(CAST(tags AS VARCHAR) AS JSON) as tags FROM ag_catalog.cypher('tarka'::name, $$
        MATCH (n) WHERE n.tenant_id = $tenant_id AND n.external_id = $external_id
        RETURN n.tags
    $$::cstring, $1::ag_catalog.agtype) as (tags ag_catalog.agtype);
    """
    params_json = json.dumps({"tenant_id": tenant_id, "external_id": external_id})
    async with _acquire() as conn:
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
    get_allowed_rels(tenant_id)
    rel = require_etype(tenant_id, relationship)
    rel = _sanitize_rel(rel)
    create_props = link_props_for_create(properties)
    match_props = link_props_for_match(properties)
    create_sql = _set_literals("r", create_props)
    match_sql = _set_literals("r", match_props)
    tid = _cypher_lit(tenant_id)
    src = _cypher_lit(from_external_id)
    dst = _cypher_lit(to_external_id)
    ends = (
        f"MATCH (a) WHERE a.tenant_id = {tid} AND a.external_id = {src} "
        f"MATCH (b) WHERE b.tenant_id = {tid} AND b.external_id = {dst}"
    )
    q_meta = _cypher_sql(
        f"{ends} RETURN labels(a), labels(b)",
        "la ag_catalog.agtype, lb ag_catalog.agtype",
        "CAST(la AS VARCHAR) as la, CAST(lb AS VARCHAR) as lb",
    )
    # ponytail: AGE 1.6 has no ON CREATE/ON MATCH and param WHERE is broken.
    q_exist = _cypher_sql(
        f"{ends} MATCH (a)-[r:{rel}]->(b) RETURN id(r)",
        "gid ag_catalog.agtype",
        "CAST(gid AS VARCHAR) as gid",
    )
    q_update = (
        _cypher_sql(
            f"{ends} MATCH (a)-[r:{rel}]->(b) SET {match_sql} RETURN r", "r ag_catalog.agtype"
        )
        if match_sql
        else None
    )
    create_set = f" SET {create_sql}" if create_sql else ""
    q_create = _cypher_sql(
        f"{ends} CREATE (a)-[r:{rel}]->(b){create_set} RETURN r",
        "r ag_catalog.agtype",
    )

    async with _acquire() as conn:
        row = await conn.fetchrow(q_meta)
        if row:
            la = _parse_age_graph_value(row["la"]) or []
            lb = _parse_age_graph_value(row["lb"]) or []
            validate_typed_edge_or_raise(tenant_id, rel, la, lb)
        existing = await conn.fetchrow(q_exist)
        if existing and existing["gid"] and existing["gid"] != "null":
            if q_update:
                await conn.execute(q_update)
            return
        try:
            await conn.execute(q_create)
        except asyncpg.DuplicateTableError:
            # First concurrent link for a relationship label: AGE's CREATE
            # edge-table DDL races under parallel writers (label table is
            # created lazily on first use). The edge did not exist when we
            # checked, another writer created the label concurrently; retry
            # the create once — the label now exists so it cannot race again.
            await conn.execute(q_create)


async def delete_entity(tenant_id: str, external_id: str) -> None:
    tid = _cypher_lit(tenant_id)
    eid = _cypher_lit(external_id)
    q = _cypher_sql(
        f"MATCH (n) WHERE n.tenant_id = {tid} AND n.external_id = {eid} DETACH DELETE n RETURN 1",
        "ok ag_catalog.agtype",
        "CAST(ok AS VARCHAR) as ok",
    )
    async with _acquire() as conn:
        await conn.execute(q)


async def list_one_hop_ids(tenant_id: str, entity_id: str) -> list[str]:
    # Two-phase directed walk. Phase 1 resolves the anchor's graphid via the
    # per-label (tenant_id, external_id) indexes; phase 2 runs two DIRECTED
    # edge lookups anchored on id(n) = <const> using ix_<label>_start/_end.
    # The old single undirected query — (e.start=n AND e.end=m) OR
    # (e.end=n AND e.start=m) with property filters on both endpoints —
    # forced a nested-loop cross product over the edge space (planner cost
    # ~8.9e8 at 100k entities). See tests/test_subgraph_plan_shape.py.
    tid = _cypher_lit(tenant_id)
    eid = _cypher_lit(entity_id)
    q_gid = _cypher_sql(
        f"MATCH (n) WHERE n.tenant_id = {tid} AND n.external_id = {eid} RETURN id(n)",
        "gid ag_catalog.agtype",
        "CAST(gid AS VARCHAR) as gid",
    )
    async with _acquire() as conn:
        grow = await conn.fetchrow(q_gid)
    if not grow or not grow.get("gid") or grow["gid"] == "null":
        return []
    gid = grow["gid"].strip().strip('"')
    out: list[str] = []
    for anchor_col in ("start_id", "end_id"):
        q = _cypher_sql(
            f"MATCH (n)-[r]->(m) WHERE id(n) = {gid} AND m.tenant_id = {tid} "
            "RETURN DISTINCT m.external_id"
            if anchor_col == "start_id"
            else f"MATCH (m)-[r]->(n) WHERE id(n) = {gid} AND m.tenant_id = {tid} "
            "RETURN DISTINCT m.external_id",
            "id ag_catalog.agtype",
            "CAST(id AS VARCHAR) as id",
        )
        async with _acquire() as conn:
            rows = await conn.fetch(q)
        for row in rows or []:
            ext = _parse_age_graph_value(row["id"])
            if ext:
                out.append(str(ext))
    return out


async def load_peer_p90_by_label(tenant_id: str, label: str) -> int | None:
    from .graph_runtime import parse_p90_degree_by_label

    try:
        pool = await get_pool()
        q = """
        SELECT CAST(CAST(raw AS VARCHAR) AS JSON) as raw
        FROM ag_catalog.cypher('tarka'::name, $$
            MATCH (s:GraphRiskStats) WHERE s.tenant_id = $tenant_id
            RETURN s.p90_degree_by_label
        $$::cstring, $1::ag_catalog.agtype) as (raw ag_catalog.agtype);
        """
        async with _acquire() as conn:
            row = await conn.fetchrow(q, json.dumps({"tenant_id": tenant_id}))
        if not row or not row["raw"] or row["raw"] == "null":
            return None
        raw = json.loads(row["raw"])
        return parse_p90_degree_by_label(raw, label)
    except Exception:
        return None


async def set_entity_risk_properties(tenant_id: str, entity_id: str, props: dict[str, Any]) -> None:
    pool = await get_pool()
    # AGE raises "Entity failed to be updated" when SET assigns a null param,
    # so only set the properties this payload actually carries.
    available = {
        "risk_score": props.get("risk_score"),
        "risk_factors": list(props.get("risk_factors") or []),
        "risk_computed_at": props.get("risk_computed_at"),
        "relation_count": props.get("relation_count"),
        "relation_growth_1h": props.get("relation_growth_1h"),
        "relation_growth_24h": props.get("relation_growth_24h"),
    }
    present = {k: v for k, v in available.items() if v is not None}
    if not present:
        return
    assignments = ", ".join(f"n.{key} = ${key}" for key in present)
    q = f"""
    SELECT * FROM ag_catalog.cypher('tarka'::name, $$
        MATCH (n) WHERE n.tenant_id = $tenant_id AND n.external_id = $entity_id
        SET {assignments}
        RETURN n
    $$::cstring, $1::ag_catalog.agtype) as (n ag_catalog.agtype);
    """
    params_json = json.dumps({"tenant_id": tenant_id, "entity_id": entity_id, **present})
    async with _acquire() as conn:
        await conn.execute(q, params_json)


async def set_entity_risk_properties_many(tenant_id: str, batch: list[dict[str, Any]]) -> int:
    """Batched entity-risk SET: one UNWIND round-trip for N entities.

    Same write semantics as set_entity_risk_properties (only present props,
    MATCH-scoped per entity); literals per the AGE 1.6 convention.
    Returns the number of entities written.
    """
    rows: list[dict[str, Any]] = []
    for item in batch:
        if not item or not is_found_payload(item):
            continue
        props = {
            "eid": str(item.get("entity_id") or ""),
            "risk_score": item.get("risk_score"),
            "risk_factors": [str(x) for x in (item.get("risk_factors") or [])],
            "risk_computed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "relation_count": _int_or_none(item.get("relation_count")),
            "relation_growth_1h": _int_or_none(item.get("relation_growth_1h")),
            "relation_growth_24h": _int_or_none(item.get("relation_growth_24h")),
        }
        if not props["eid"]:
            continue
        props = {k: v for k, v in props.items() if v is not None}
        props["eid"] = str(item.get("entity_id") or "")
        rows.append(props)
    if not rows:
        return 0
    tid = _cypher_lit(tenant_id)
    payload = json.dumps({"rows": rows})
    q = f"""
    SELECT count(n) AS c
    FROM ag_catalog.cypher('tarka'::name, $$
        UNWIND $rows AS row
        MATCH (n) WHERE n.tenant_id = {tid} AND n.external_id = row.eid
        SET n.risk_score = row.risk_score,
            n.risk_factors = row.risk_factors,
            n.risk_computed_at = row.risk_computed_at,
            n.relation_count = row.relation_count,
            n.relation_growth_1h = row.relation_growth_1h,
            n.relation_growth_24h = row.relation_growth_24h
        RETURN n
    $$::cstring, $1::ag_catalog.agtype) as (n ag_catalog.agtype);
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(q, payload)
    return len(rows)


def _int_or_none(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _node_to_dict(n: dict[str, Any]) -> dict[str, Any]:
    props = n.get("properties") if isinstance(n.get("properties"), dict) else {}
    eid = str(props.get("external_id") or n.get("id") or "")
    label = n.get("label")
    labels = [label] if label else [str(x) for x in (n.get("labels") or []) if x]
    return decorate_subgraph_node(
        {
            "id": eid,
            "labels": labels,
            "properties": props,
        }
    )


def _node_tenant_id(node: dict[str, Any]) -> str:
    props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    return str(props.get("tenant_id") or "")


async def query_subgraph(tenant_id: str, entity_id: str, depth: int) -> dict[str, Any]:
    # ponytail: AGE 1.6 has no age_unnest / variable-length UNWIND. D7.4 Path B:
    # the default walk stays 1-hop. Depth-2 (opt-in via HUNT_DEPTH_2_ENABLED in
    # hunt_depth.hunt_walk_depth, which produces depth==2 here) is an EXPLICIT
    # second edge pattern - never a variable-length `[*1..n]`.
    from .hunt_depth import hunt_walk_depth

    walk = hunt_walk_depth(depth)
    tid = _cypher_lit(tenant_id)
    eid = _cypher_lit(entity_id)
    # Two-phase directed walk (see list_one_hop_ids): resolve anchor graphid,
    # then DIRECTED per-direction edge lookups anchored on id() = const.
    # The previous single undirected OR-join nested-looped the edge space
    # (cost ~8.9e8 at 100k entities) — tests/test_subgraph_plan_shape.py.
    q_root = _cypher_sql(
        f"MATCH (root) WHERE root.tenant_id = {tid} AND root.external_id = {eid} "
        "RETURN root, id(root)",
        "root ag_catalog.agtype, gid ag_catalog.agtype",
        "CAST(root AS VARCHAR) as root, CAST(gid AS VARCHAR) as gid",
    )
    async with _acquire() as conn:
        root_rows = await conn.fetch(q_root)
    if not root_rows:
        return {"nodes": [], "edges": []}
    gid_raw = root_rows[0].get("gid")
    if not gid_raw or gid_raw == "null":
        return {"nodes": [], "edges": []}
    gid = gid_raw.strip().strip('"')
    q_hop_fwd = _cypher_sql(
        f"MATCH (root)-[e]->(nb) WHERE id(root) = {gid} AND nb.tenant_id = {tid} RETURN e, nb",
        "e ag_catalog.agtype, nb ag_catalog.agtype",
        "CAST(e AS VARCHAR) as e, CAST(nb AS VARCHAR) as nb",
    )
    q_hop_rev = _cypher_sql(
        f"MATCH (nb)-[e]->(root) WHERE id(root) = {gid} AND nb.tenant_id = {tid} RETURN e, nb",
        "e ag_catalog.agtype, nb ag_catalog.agtype",
        "CAST(e AS VARCHAR) as e, CAST(nb AS VARCHAR) as nb",
    )
    q_hop2_fwd = (
        _cypher_sql(
            f"MATCH (root)-[e1]->(nb1)-[e2]->(nb2) WHERE id(root) = {gid} "
            f"AND nb1.tenant_id = {tid} AND nb2.tenant_id = {tid} "
            f"AND id(nb2) <> id(root) RETURN e1, nb1, e2, nb2",
            "e1 ag_catalog.agtype, nb1 ag_catalog.agtype, e2 ag_catalog.agtype, nb2 ag_catalog.agtype",
            "CAST(e1 AS VARCHAR) as e1, CAST(nb1 AS VARCHAR) as nb1, "
            "CAST(e2 AS VARCHAR) as e2, CAST(nb2 AS VARCHAR) as nb2",
        )
        if walk >= 2
        else None
    )
    q_hop2_rev = (
        _cypher_sql(
            f"MATCH (nb2)-[e2]->(nb1)-[e1]->(root) WHERE id(root) = {gid} "
            f"AND nb1.tenant_id = {tid} AND nb2.tenant_id = {tid} "
            f"AND id(nb2) <> id(root) RETURN e1, nb1, e2, nb2",
            "e1 ag_catalog.agtype, nb1 ag_catalog.agtype, e2 ag_catalog.agtype, nb2 ag_catalog.agtype",
            "CAST(e1 AS VARCHAR) as e1, CAST(nb1 AS VARCHAR) as nb1, "
            "CAST(e2 AS VARCHAR) as e2, CAST(nb2 AS VARCHAR) as nb2",
        )
        if walk >= 2
        else None
    )
    nodes_out: list[dict[str, Any]] = []
    edges_out: list[dict[str, Any]] = []
    seen_nodes: set[str] = set()
    seen_edges: set[str] = set()
    graph_to_ext: dict[str, str] = {}

    async with _acquire() as conn:
        hop_rows = await conn.fetch(q_hop_fwd)
        hop_rows += await conn.fetch(q_hop_rev)
        hop2_rows = []
        if q_hop2_fwd is not None:
            hop2_rows += await conn.fetch(q_hop2_fwd)
            hop2_rows += await conn.fetch(q_hop2_rev)
    rows = []
    if root_rows:
        rows.append({"root": root_rows[0]["root"], "e": None, "nb": None})
    for hop in hop_rows or []:
        rows.append({"root": None, "e": hop["e"], "nb": hop["nb"]})
    for hop in hop2_rows or []:
        # second hop: carry first-hop node/edge alongside so the dedup pass links them
        rows.append({"root": None, "e": hop["e1"], "nb": hop["nb1"]})
        rows.append({"root": None, "e": hop["e2"], "nb": hop["nb2"]})

    for row in rows or []:
        for key in ("root", "nb"):
            raw = _parse_age_graph_value(row[key])
            if not isinstance(raw, dict):
                continue
            node = _node_to_dict(raw)
            nid = str(node.get("id") or "")
            node_tenant = _node_tenant_id(node)
            if node_tenant and node_tenant != tenant_id:
                continue
            gid = str(raw.get("id") or "")
            if gid and nid:
                graph_to_ext[gid] = nid
            if nid and nid not in seen_nodes:
                seen_nodes.add(nid)
                nodes_out.append(node)
        raw_e = _parse_age_graph_value(row["e"])
        if not isinstance(raw_e, dict):
            continue
        eid = str(raw_e.get("id") or "")
        if not eid or eid in seen_edges:
            continue
        seen_edges.add(eid)
        start = str(raw_e.get("start_id") or raw_e.get("startNode") or "")
        end = str(raw_e.get("end_id") or raw_e.get("endNode") or "")
        from_ext = graph_to_ext.get(start, start)
        to_ext = graph_to_ext.get(end, end)
        if from_ext not in seen_nodes or to_ext not in seen_nodes:
            continue
        edges_out.append(
            {
                "id": eid,
                "type": raw_e.get("label"),
                "startNode": from_ext,
                "endNode": to_ext,
                "from_id": from_ext,
                "to_id": to_ext,
                "properties": raw_e.get("properties")
                if isinstance(raw_e.get("properties"), dict)
                else {},
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


def _parse_age_graph_value(raw: Any) -> Any:
    if raw is None or raw == "null":
        return None
    text = raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
    text = text.strip()
    for suffix in ("::vertex", "::edge", "::path"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return _age_json(text)


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
    FROM ag_catalog.cypher('tarka'::name, $$
        MATCH (n) WHERE n.tenant_id = $tenant_id
        WHERE n.risk_computed_at IS NOT NULL AND n.risk_score >= $min_score
        RETURN n.external_id, labels(n), n.risk_score, n.risk_factors,
               n.risk_computed_at, n.relation_count, n.relation_growth_1h, n.relation_growth_24h
        ORDER BY n.risk_score DESC, n.external_id ASC
        LIMIT {int(limit)}
    $$::cstring, $1::ag_catalog.agtype) as (
        entity_id ag_catalog.agtype, labels ag_catalog.agtype, risk_score ag_catalog.agtype, risk_factors ag_catalog.agtype,
        risk_computed_at ag_catalog.agtype, relation_count ag_catalog.agtype, relation_growth_1h ag_catalog.agtype,
        relation_growth_24h agtype
    );
    """
    params_json = json.dumps({"tenant_id": tenant_id, "min_score": min_score})
    async with _acquire() as conn:
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


async def search_entities(
    tenant_id: str, q: str, label: str | None = None, limit: int = 20
) -> tuple[list[dict[str, Any]], bool]:
    from .search_keys import search_prefix

    sql = await search_prefix(tenant_id, q, label=label, limit=limit)
    if sql is None:
        return [], False
    return sql


async def _search_entities_scan_fallback(
    tenant_id: str, q: str, label: str | None = None, limit: int = 20
) -> tuple[list[dict[str, Any]], bool]:
    from .entity_risk_score import (
        cap_identifier_owners,
        clamp_search_limit,
        eligible_search_node,
        labels_are_identifier,
        labels_are_owner,
        merge_search_hits,
        search_hit_from_node,
    )

    limit = clamp_search_limit(limit)
    needle = str(q or "")
    if not needle.strip():
        return [], False
    tid = _cypher_lit(tenant_id)
    # ponytail: AGE 1.6 param WHERE via asyncpg is broken; tenant is a literal, q is Python.
    match_stmt = _cypher_sql(
        f"MATCH (n) WHERE n.tenant_id = {tid} "
        "AND n.external_id IS NOT NULL AND n.external_id <> '' "
        "RETURN n.external_id, labels(n), properties(n)",
        "entity_id ag_catalog.agtype, labels ag_catalog.agtype, props agtype",
        "CAST(CAST(entity_id AS VARCHAR) AS JSON) as entity_id, "
        "CAST(CAST(labels AS VARCHAR) AS JSON) as labels, "
        "CAST(CAST(props AS VARCHAR) AS JSON) as props",
    )
    async with _acquire() as conn:
        rows = await conn.fetch(match_stmt)
    directs: list[dict[str, Any]] = []
    ident_ids: list[str] = []
    ident_meta: dict[str, dict[str, Any]] = {}
    for rec in rows or []:
        if not rec:
            continue
        eid = str(_age_json(rec["entity_id"]) or "").strip()
        labs = _age_json(rec["labels"]) or []
        if not isinstance(labs, list):
            labs = [labs] if labs else []
        if "GraphRiskStats" in labs:
            continue
        props = _age_json(rec["props"]) or {}
        if not isinstance(props, dict):
            props = dict(props)
        matched = eligible_search_node(eid, props, needle)
        if not matched:
            continue
        hit = search_hit_from_node(tenant_id, eid, labs, props, matched_on=matched, via=None)
        directs.append(hit)
        if labels_are_identifier(labs):
            ident_ids.append(eid)
            ident_meta[eid] = hit
    owners: list[dict[str, Any]] = []
    if ident_ids:
        ident_set = set(ident_ids)
        owner_stmt = _cypher_sql(
            f"MATCH (n)-[r]-(m) WHERE n.tenant_id = {tid} AND m.tenant_id = {tid} "
            "AND n.external_id IS NOT NULL AND m.external_id IS NOT NULL "
            "RETURN n.external_id, m.external_id, labels(m), properties(m)",
            "via_id ag_catalog.agtype, entity_id ag_catalog.agtype, labels ag_catalog.agtype, props agtype",
            "CAST(CAST(via_id AS VARCHAR) AS JSON) as via_id, "
            "CAST(CAST(entity_id AS VARCHAR) AS JSON) as entity_id, "
            "CAST(CAST(labels AS VARCHAR) AS JSON) as labels, "
            "CAST(CAST(props AS VARCHAR) AS JSON) as props",
        )
        async with _acquire() as conn:
            orows = await conn.fetch(owner_stmt)
        raw_owners: list[dict[str, Any]] = []
        for rec in orows or []:
            if not rec:
                continue
            via = str(_age_json(rec["via_id"]) or "")
            if via not in ident_set:
                continue
            ident = ident_meta.get(via)
            if not ident:
                continue
            eid = str(_age_json(rec["entity_id"]) or "").strip()
            labs = _age_json(rec["labels"]) or []
            if not isinstance(labs, list):
                labs = [labs] if labs else []
            if "GraphRiskStats" in labs:
                continue
            if not eid or not labels_are_owner(labs):
                continue
            props = _age_json(rec["props"]) or {}
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


async def scan_tenant_entity_ids(tenant_id: str, limit: int) -> tuple[list[str], bool]:
    from .entity_risk_writeback import clamp_refresh_limit

    limit = clamp_refresh_limit(limit)
    fetch = int(limit) + 1
    pool = await get_pool()
    q = f"""
    SELECT CAST(CAST(entity_id AS VARCHAR) AS JSON) as entity_id
    FROM ag_catalog.cypher('tarka'::name, $$
        MATCH (n) WHERE n.tenant_id = $tenant_id AND n.external_id IS NOT NULL
        RETURN n.external_id
        ORDER BY n.external_id ASC
        LIMIT {fetch}
    $$::cstring, $1::ag_catalog.agtype) as (entity_id ag_catalog.agtype);
    """
    async with _acquire() as conn:
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
    SELECT * FROM ag_catalog.cypher('tarka'::name, $$
        MERGE (s:GraphRiskStats {tenant_id: $tenant_id})
        SET s.p90_degree_by_label = $p90_json,
            s.stats_computed_at = $stats_computed_at
        RETURN s
    $$::cstring, $1::ag_catalog.agtype) as (s ag_catalog.agtype);
    """
    params_json = json.dumps(
        {
            "tenant_id": tenant_id,
            "p90_json": json.dumps(p90_degree_by_label or {}),
            "stats_computed_at": stats_computed_at,
        }
    )
    async with _acquire() as conn:
        await conn.execute(q, params_json)
