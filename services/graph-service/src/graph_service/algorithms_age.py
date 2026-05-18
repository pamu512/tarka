from __future__ import annotations

import json
from graph_service.age_client import get_pool

"""
Graph analytics functions using Apache AGE via asyncpg.
"""


def _clamp_depth(depth: int) -> int:
    return max(1, min(int(depth), 5))


# ---------------------------------------------------------------------------
# a) Community Detection
# ---------------------------------------------------------------------------


async def detect_communities(
    tenant_id: str,
    min_community_size: int = 3,
) -> list[dict]:
    pool = await get_pool()

    # AGE does not support variable length paths in the same way as Neo4j with all functions
    # We will use a simplified approach or standard cypher that AGE supports
    q = """
    SELECT CAST(CAST(canonical_key AS VARCHAR) AS JSON) as canonical_key,
           CAST(CAST(member_ids AS VARCHAR) AS JSON) as member_ids,
           CAST(CAST(all_labels AS VARCHAR) AS JSON) as all_labels,
           CAST(CAST(all_tags_lists AS VARCHAR) AS JSON) as all_tags_lists,
           CAST(CAST(cnt AS VARCHAR) AS JSON) as cnt
    FROM cypher('tarka', $$
        MATCH (n {tenant_id: $tenant_id})
        WITH collect(n) AS all_nodes
        UNWIND all_nodes AS seed
        OPTIONAL MATCH path = (seed)-[*1..5]-(peer)
        WHERE peer.tenant_id = $tenant_id
        WITH seed,
             [seed] + collect(DISTINCT peer) AS component
        WITH seed,
             component,
             reduce(
               ids = [],
               m IN component |
               CASE WHEN m.external_id IN ids THEN ids
                    ELSE ids + [m.external_id] END
             ) AS raw_ids
        WITH seed, component, raw_ids
        ORDER BY raw_ids[0]
        WITH raw_ids                          AS canonical_key,
             collect(seed)[0]                 AS representative,
             collect(DISTINCT seed)           AS seeds,
             head(collect(component))         AS members
        WITH canonical_key,
             [m IN members | m.external_id]   AS member_ids,
             [m IN members | labels(m)]       AS all_labels,
             [m IN members |
               CASE WHEN m.tags IS NOT NULL THEN m.tags ELSE [] END
             ]                                AS all_tags_lists,
             size(members)                    AS cnt
        WHERE cnt >= $min_size
        RETURN canonical_key,
               member_ids,
               all_labels,
               all_tags_lists,
               cnt
        ORDER BY cnt DESC
    $$, %s) as (canonical_key agtype, member_ids agtype, all_labels agtype, all_tags_lists agtype, cnt agtype);
    """

    params_json = json.dumps({"tenant_id": tenant_id, "min_size": min_community_size})

    seen_keys: set[str] = set()
    communities: list[dict] = []
    idx = 0

    async with pool.acquire() as conn:
        rows = await conn.fetch(q, params_json)

        for row in rows:
            if not row["member_ids"] or row["member_ids"] == "null":
                continue
            member_ids = json.loads(row["member_ids"])
            key = "|".join(sorted(member_ids))
            if key in seen_keys:
                continue
            seen_keys.add(key)

            all_labels = (
                json.loads(row["all_labels"])
                if row["all_labels"] and row["all_labels"] != "null"
                else []
            )
            all_tags_lists = (
                json.loads(row["all_tags_lists"])
                if row["all_tags_lists"] and row["all_tags_lists"] != "null"
                else []
            )

            flat_labels = {lbl for label_list in all_labels for lbl in label_list}
            flat_tags = {t for tag_list in all_tags_lists for t in tag_list}

            communities.append(
                {
                    "community_id": idx,
                    "member_count": json.loads(row["cnt"]),
                    "member_ids": member_ids,
                    "member_labels": sorted(flat_labels),
                    "shared_attributes": sorted(flat_tags),
                }
            )
            idx += 1

    return communities


# ---------------------------------------------------------------------------
# b) Risk Propagation
# ---------------------------------------------------------------------------


async def propagate_risk(
    tenant_id: str,
    entity_id: str,
    depth: int = 3,
    decay: float = 0.5,
) -> list[dict]:
    depth = _clamp_depth(depth)
    pool = await get_pool()

    q = f"""
    SELECT CAST(CAST(entity_id AS VARCHAR) AS JSON) as entity_id,
           CAST(CAST(entity_labels AS VARCHAR) AS JSON) as entity_labels,
           CAST(CAST(distance AS VARCHAR) AS JSON) as distance,
           CAST(CAST(rel_types AS VARCHAR) AS JSON) as rel_types,
           CAST(CAST(node_chain AS VARCHAR) AS JSON) as node_chain
    FROM cypher('tarka', $$
        MATCH (root {{tenant_id: $tenant_id, external_id: $entity_id}})
        MATCH path = (root)-[*1..{depth}]-(neighbor)
        WHERE neighbor.tenant_id = $tenant_id
          AND neighbor.external_id <> $entity_id
        WITH neighbor,
             min(length(path)) AS distance,
             [r IN relationships(path) | type(r)]  AS rel_types,
             [n IN nodes(path)        | n.external_id] AS node_chain
        RETURN DISTINCT
               neighbor.external_id AS entity_id,
               labels(neighbor)     AS entity_labels,
               distance,
               rel_types,
               node_chain
        ORDER BY distance
    $$, %s) as (entity_id agtype, entity_labels agtype, distance agtype, rel_types agtype, node_chain agtype);
    """

    params_json = json.dumps({"tenant_id": tenant_id, "entity_id": entity_id})

    seen: set[str] = set()
    entities: list[dict] = []

    async with pool.acquire() as conn:
        rows = await conn.fetch(q, params_json)

        for row in rows:
            if not row["entity_id"] or row["entity_id"] == "null":
                continue
            eid = json.loads(row["entity_id"])
            if eid in seen:
                continue
            seen.add(eid)

            dist = json.loads(row["distance"])
            score = round(100.0 * (decay**dist), 2)
            rel_types = (
                json.loads(row["rel_types"])
                if row["rel_types"] and row["rel_types"] != "null"
                else []
            )
            node_chain = (
                json.loads(row["node_chain"])
                if row["node_chain"] and row["node_chain"] != "null"
                else []
            )

            path_desc = " -> ".join(
                f"({nid})"
                if i % 2 == 0
                else f"-[{rel_types[i // 2] if i // 2 < len(rel_types) else '?'}]->"
                for i, nid in enumerate(node_chain)
            )

            entities.append(
                {
                    "entity_id": eid,
                    "entity_labels": json.loads(row["entity_labels"])
                    if row["entity_labels"] and row["entity_labels"] != "null"
                    else [],
                    "propagated_risk_score": score,
                    "distance": dist,
                    "path_description": path_desc,
                }
            )

    return entities


# ---------------------------------------------------------------------------
# c) Shared Attribute Detection
# ---------------------------------------------------------------------------


async def find_shared_attributes(
    tenant_id: str,
    attribute: str = "device_id",
    min_shared: int = 2,
) -> list[dict]:
    import re

    if not re.match(r"^[A-Za-z][A-Za-z0-9_]{0,63}$", attribute):
        raise ValueError(f"Invalid attribute name: {attribute!r}")

    pool = await get_pool()

    q = f"""
    SELECT CAST(CAST(attr_value AS VARCHAR) AS JSON) as attr_value,
           CAST(CAST(entities AS VARCHAR) AS JSON) as entities,
           CAST(CAST(group_size AS VARCHAR) AS JSON) as group_size
    FROM cypher('tarka', $$
        MATCH (n {{tenant_id: $tenant_id}})
        WHERE n.`{attribute}` IS NOT NULL
        WITH n.`{attribute}` AS attr_value, collect(n.external_id) AS entities
        WHERE size(entities) >= $min_shared
        RETURN attr_value, entities, size(entities) AS group_size
        ORDER BY group_size DESC
    $$, %s) as (attr_value agtype, entities agtype, group_size agtype);
    """

    params_json = json.dumps({"tenant_id": tenant_id, "min_shared": min_shared})

    results = []
    async with pool.acquire() as conn:
        rows = await conn.fetch(q, params_json)
        for row in rows:
            if not row["attr_value"] or row["attr_value"] == "null":
                continue
            results.append(
                {
                    "attribute": attribute,
                    "shared_value": str(json.loads(row["attr_value"])),
                    "entity_ids": json.loads(row["entities"])
                    if row["entities"] and row["entities"] != "null"
                    else [],
                    "group_size": json.loads(row["group_size"]),
                }
            )

    return results


# ---------------------------------------------------------------------------
# d) Fraud Ring Detection
# ---------------------------------------------------------------------------


async def detect_fraud_rings(
    tenant_id: str,
    min_ring_size: int = 3,
) -> list[dict]:
    min_ring_size = max(3, min(min_ring_size, 6))
    max_ring = 6
    pool = await get_pool()

    q = f"""
    SELECT CAST(CAST(node_ids AS VARCHAR) AS JSON) as node_ids,
           CAST(CAST(rel_types AS VARCHAR) AS JSON) as rel_types,
           CAST(CAST(ring_len AS VARCHAR) AS JSON) as ring_len,
           CAST(CAST(all_tags AS VARCHAR) AS JSON) as all_tags
    FROM cypher('tarka', $$
        MATCH path = (a {{tenant_id: $tenant_id}})-[*{min_ring_size}..{max_ring}]-(a)
        WHERE ALL(n IN nodes(path) WHERE n.tenant_id = $tenant_id)
        WITH nodes(path) AS ring_nodes,
             relationships(path) AS ring_rels,
             length(path) AS ring_len
        WITH ring_nodes, ring_rels, ring_len,
             [n IN ring_nodes | n.external_id] AS node_ids,
             [r IN ring_rels  | type(r)]       AS rel_types,
             reduce(
               tags = [],
               n IN ring_nodes |
               tags + CASE WHEN n.tags IS NOT NULL THEN n.tags ELSE [] END
             ) AS all_tags
        RETURN DISTINCT node_ids, rel_types, ring_len, all_tags
        ORDER BY ring_len
        LIMIT 50
    $$, %s) as (node_ids agtype, rel_types agtype, ring_len agtype, all_tags agtype);
    """

    params_json = json.dumps({"tenant_id": tenant_id})

    seen: set[str] = set()
    rings: list[dict] = []

    async with pool.acquire() as conn:
        rows = await conn.fetch(q, params_json)
        for row in rows:
            if not row["node_ids"] or row["node_ids"] == "null":
                continue
            ids = json.loads(row["node_ids"])
            canon = "|".join(sorted(set(ids)))
            if canon in seen:
                continue
            seen.add(canon)

            unique_ids = list(dict.fromkeys(ids))
            if len(unique_ids) < min_ring_size:
                continue

            all_tags = (
                json.loads(row["all_tags"]) if row["all_tags"] and row["all_tags"] != "null" else []
            )
            rel_types = (
                json.loads(row["rel_types"])
                if row["rel_types"] and row["rel_types"] != "null"
                else []
            )

            rings.append(
                {
                    "ring_members": unique_ids,
                    "ring_size": len(unique_ids),
                    "relationships": rel_types,
                    "aggregate_tags": sorted(set(all_tags)),
                }
            )

    return rings


# ---------------------------------------------------------------------------
# e) Entity Risk Score
# ---------------------------------------------------------------------------

_HIGH_RISK_TAGS = frozenset(
    {
        "fraud",
        "suspicious",
        "flagged",
        "blocked",
        "chargedback",
    }
)


async def compute_entity_risk(
    tenant_id: str,
    entity_id: str,
    *,
    checkpoint: str | None = None,
) -> dict:
    from graph_service.checkpoint_registry import resolve_profile

    profile = resolve_profile(checkpoint)
    mult = float(profile.get("risk_score_multiplier") or 1.0)
    hop_depth = _clamp_depth(int(profile.get("max_neighbor_hops") or 3))

    pool = await get_pool()

    q = f"""
    SELECT CAST(CAST(tags AS VARCHAR) AS JSON) as tags,
           CAST(CAST(conn_count AS VARCHAR) AS JSON) as conn_count,
           CAST(CAST(flagged_neighbors AS VARCHAR) AS JSON) as flagged_neighbors,
           CAST(CAST(community_size AS VARCHAR) AS JSON) as community_size,
           CAST(CAST(shared_device_count AS VARCHAR) AS JSON) as shared_device_count
    FROM cypher('tarka', $$
        MATCH (n {{tenant_id: $tenant_id, external_id: $entity_id}})

        OPTIONAL MATCH (n)-[r]-(neighbor)
        WHERE neighbor.tenant_id = $tenant_id
        WITH n,
             count(DISTINCT neighbor) AS conn_count,
             collect(DISTINCT neighbor) AS neighbors

        WITH n, conn_count, neighbors,
             size([nb IN neighbors
                   WHERE ANY(t IN COALESCE(nb.tags, [])
                             WHERE t IN $high_risk_tags)
             ]) AS flagged_neighbors

        OPTIONAL MATCH (n)-[*1..{hop_depth}]-(community_member)
        WHERE community_member.tenant_id = $tenant_id
        WITH n, conn_count, flagged_neighbors,
             count(DISTINCT community_member) + 1 AS community_size

        OPTIONAL MATCH (other {{tenant_id: $tenant_id}})
        WHERE other.external_id <> $entity_id
          AND other.device_id IS NOT NULL
          AND n.device_id IS NOT NULL
          AND other.device_id = n.device_id
        WITH n, conn_count, flagged_neighbors, community_size,
             count(DISTINCT other) AS shared_device_count

        RETURN
          n.tags              AS tags,
          conn_count,
          flagged_neighbors,
          community_size,
          shared_device_count
    $$, %s) as (tags agtype, conn_count agtype, flagged_neighbors agtype, community_size agtype, shared_device_count agtype);
    """

    params_json = json.dumps(
        {"tenant_id": tenant_id, "entity_id": entity_id, "high_risk_tags": sorted(_HIGH_RISK_TAGS)}
    )

    async with pool.acquire() as conn:
        row = await conn.fetchrow(q, params_json)

    if not row or not row["conn_count"] or row["conn_count"] == "null":
        return {
            "entity_id": entity_id,
            "risk_score": 0,
            "risk_factors": ["entity_not_found"],
            "connected_flagged_count": 0,
            "community_size": 0,
            "graph_checkpoint": checkpoint,
            "graph_profile": profile.get("_profile_name"),
            "graph_profile_max_neighbor_hops": hop_depth,
        }

    tags = json.loads(row["tags"]) if row["tags"] and row["tags"] != "null" else []
    conn_count: int = json.loads(row["conn_count"])
    flagged: int = json.loads(row["flagged_neighbors"])
    community_size: int = json.loads(row["community_size"])
    shared_devices: int = json.loads(row["shared_device_count"])

    score = 0.0
    factors: list[str] = []

    own_risky = _HIGH_RISK_TAGS & set(tags)
    if own_risky:
        score += 30
        factors.append(f"own_tags:{','.join(sorted(own_risky))}")

    if flagged > 0:
        score += min(flagged * 10, 25)
        factors.append(f"connected_flagged:{flagged}")

    if community_size >= 5:
        score += 15
        factors.append(f"large_community:{community_size}")
    elif community_size >= 3:
        score += 8
        factors.append(f"medium_community:{community_size}")

    if shared_devices > 0:
        score += min(shared_devices * 10, 20)
        factors.append(f"shared_devices:{shared_devices}")

    if conn_count >= 10:
        score += 10
        factors.append(f"high_connectivity:{conn_count}")
    elif conn_count >= 5:
        score += 5
        factors.append(f"moderate_connectivity:{conn_count}")

    score = min(round(score * mult), 100)

    return {
        "entity_id": entity_id,
        "risk_score": score,
        "risk_factors": factors,
        "connected_flagged_count": flagged,
        "community_size": community_size,
        "graph_checkpoint": checkpoint,
        "graph_profile": profile.get("_profile_name"),
        "graph_profile_multiplier": mult,
        "graph_profile_max_neighbor_hops": hop_depth,
    }
