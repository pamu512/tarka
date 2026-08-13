from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from .entity_risk_score import entity_not_found_payload, score_entity_risk
from .graph_data_freshness import _parse_timestamp
from .neo4j_client import get_driver

"""
Graph analytics functions using native Neo4j Cypher.

No GDS plugin required — works with neo4j:5-community.
All queries use parameterized Cypher ($params) except variable-length
path depths, which Cypher requires as literal integers (clamped to 1-5).
"""


def _clamp_depth(depth: int) -> int:
    return max(1, min(int(depth), 5))


async def _open_session(driver):
    """Handle both direct and awaitable driver.session() implementations."""
    session_cm = driver.session()
    if hasattr(session_cm, "__await__"):
        session_cm = await session_cm
    return session_cm


def _relation_growth_counts(timestamps: list[Any]) -> tuple[int, int]:
    now = datetime.now(UTC)
    g1 = g24 = 0
    for ts in timestamps:
        dt = _parse_timestamp(ts)
        if dt is None:
            continue
        delta = now - dt
        if delta <= timedelta(hours=1):
            g1 += 1
        if delta <= timedelta(hours=24):
            g24 += 1
    return g1, g24


def _growth_from_record(rec: Any) -> tuple[int, int]:
    timestamps = rec.get("edge_timestamps") if hasattr(rec, "get") else None
    if isinstance(timestamps, list):
        return _relation_growth_counts(timestamps)
    return (
        int(rec.get("relation_growth_1h") or 0),
        int(rec.get("relation_growth_24h") or 0),
    )


# ---------------------------------------------------------------------------
# a) Community Detection  (connected-component labelling via Cypher)
# ---------------------------------------------------------------------------


async def detect_communities(
    tenant_id: str,
    min_community_size: int = 3,
) -> list[dict]:
    """
    Find connected components among all nodes for a tenant.
    Each component is returned as a "community" with member info.
    """
    driver = await get_driver()

    q_native = """
    MATCH (n {tenant_id: $tenant_id})
    WITH collect(n) AS all_nodes
    UNWIND all_nodes AS seed
    OPTIONAL MATCH path = (seed)-[*1..8]-(peer)
    WHERE peer.tenant_id = $tenant_id
    WITH seed,
         [seed] + collect(DISTINCT peer) AS component
    WITH seed,
         component,
         reduce(
           ids = [],
           m IN component |
           CASE WHEN m.external_id IN ids THEN ids
                ELSE ids + m.external_id END
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
    """

    async with await _open_session(driver) as session:
        result = await session.run(
            q_native,
            tenant_id=tenant_id,
            min_size=min_community_size,
        )
        records = [r async for r in result]

    seen_keys: set[str] = set()
    communities: list[dict] = []
    idx = 0

    for rec in records:
        key = "|".join(sorted(rec["member_ids"]))
        if key in seen_keys:
            continue
        seen_keys.add(key)

        flat_labels = {lbl for label_list in rec["all_labels"] for lbl in label_list}
        flat_tags = {t for tag_list in rec["all_tags_lists"] for t in tag_list}

        communities.append(
            {
                "community_id": idx,
                "member_count": rec["cnt"],
                "member_ids": rec["member_ids"],
                "member_labels": sorted(flat_labels),
                "shared_attributes": sorted(flat_tags),
            }
        )
        idx += 1

    return communities


# ---------------------------------------------------------------------------
# b) Risk Propagation  (decaying outward traversal)
# ---------------------------------------------------------------------------


async def propagate_risk(
    tenant_id: str,
    entity_id: str,
    depth: int = 3,
    decay: float = 0.5,
) -> list[dict]:
    """
    Starting from a known-risky entity, propagate risk outward.
    Each hop multiplies the score by *decay*.
    `depth` is clamped to 1-5 and inserted as a literal (Cypher requirement).
    """
    depth = _clamp_depth(depth)
    driver = await get_driver()

    q = f"""
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
    """

    async with await _open_session(driver) as session:
        result = await session.run(
            q,
            tenant_id=tenant_id,
            entity_id=entity_id,
        )
        records = [r async for r in result]

    seen: set[str] = set()
    entities: list[dict] = []

    for rec in records:
        eid = rec["entity_id"]
        if eid in seen:
            continue
        seen.add(eid)

        dist = rec["distance"]
        score = round(100.0 * (decay**dist), 2)
        path_desc = " -> ".join(
            f"({nid})"
            if i % 2 == 0
            else f"-[{rec['rel_types'][i // 2] if i // 2 < len(rec['rel_types']) else '?'}]->"
            for i, nid in enumerate(rec["node_chain"])
        )

        entities.append(
            {
                "entity_id": eid,
                "entity_labels": rec["entity_labels"],
                "propagated_risk_score": score,
                "distance": dist,
                "path_description": path_desc,
                "node_chain": rec["node_chain"],
                "rel_types": rec["rel_types"],
            }
        )

    return entities


async def explain_paths(
    tenant_id: str,
    entity_id: str,
    depth: int = 3,
    decay: float = 0.5,
    *,
    to_entity_id: str | None = None,
    limit: int = 10,
) -> dict:
    from .path_explain import assemble_path_explanation

    rows = await propagate_risk(tenant_id, entity_id, depth=depth, decay=decay)
    subject = await compute_entity_risk(tenant_id, entity_id)
    return assemble_path_explanation(
        tenant_id,
        entity_id,
        rows,
        to_entity_id=to_entity_id,
        limit=limit,
        subject_risk=subject,
    )


# ---------------------------------------------------------------------------
# c) Shared Attribute Detection
# ---------------------------------------------------------------------------


async def find_shared_attributes(
    tenant_id: str,
    attribute: str = "device_id",
    min_shared: int = 2,
) -> list[dict]:
    """
    Find entities that share a common property value (same device, IP, etc.).
    The attribute name is validated to prevent injection.
    """
    import re

    if not re.match(r"^[A-Za-z][A-Za-z0-9_]{0,63}$", attribute):
        raise ValueError(f"Invalid attribute name: {attribute!r}")

    driver = await get_driver()

    q = f"""
    MATCH (n {{tenant_id: $tenant_id}})
    WHERE n.`{attribute}` IS NOT NULL
    WITH n.`{attribute}` AS attr_value, collect(n.external_id) AS entities
    WHERE size(entities) >= $min_shared
    RETURN attr_value, entities, size(entities) AS group_size
    ORDER BY group_size DESC
    """

    async with await _open_session(driver) as session:
        result = await session.run(
            q,
            tenant_id=tenant_id,
            min_shared=min_shared,
        )
        records = [r async for r in result]

    return [
        {
            "attribute": attribute,
            "shared_value": str(rec["attr_value"]),
            "entity_ids": rec["entities"],
            "group_size": rec["group_size"],
        }
        for rec in records
    ]


# ---------------------------------------------------------------------------
# d) Fraud Ring Detection  (cycles)
# ---------------------------------------------------------------------------


async def detect_fraud_rings(
    tenant_id: str,
    min_ring_size: int = 3,
) -> list[dict]:
    """
    Find cycles (ring patterns) among tenant entities.
    Rings are capped at length 6 to keep queries tractable.
    """
    min_ring_size = max(3, min(min_ring_size, 6))
    max_ring = 6
    driver = await get_driver()

    q = f"""
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
    """

    async with await _open_session(driver) as session:
        result = await session.run(q, tenant_id=tenant_id)
        records = [r async for r in result]

    seen: set[str] = set()
    rings: list[dict] = []

    for rec in records:
        ids = rec["node_ids"]
        canon = "|".join(sorted(set(ids)))
        if canon in seen:
            continue
        seen.add(canon)

        unique_ids = list(dict.fromkeys(ids))
        if len(unique_ids) < min_ring_size:
            continue

        rings.append(
            {
                "ring_members": unique_ids,
                "ring_size": len(unique_ids),
                "relationships": rec["rel_types"],
                "aggregate_tags": sorted(set(rec["all_tags"])),
            }
        )

    return rings


# ---------------------------------------------------------------------------
# e) Entity Risk Score
# ---------------------------------------------------------------------------


async def load_peer_p90_for_label(tenant_id: str, label: str) -> int | None:
    from .graph_runtime import parse_p90_degree_by_label

    try:
        driver = await get_driver()
        q = """
        MATCH (s:GraphRiskStats {tenant_id: $tenant_id})
        RETURN s.p90_degree_by_label AS raw
        """
        async with await _open_session(driver) as session:
            result = await session.run(q, tenant_id=tenant_id)
            rec = await result.single()
        if rec is None:
            return None
        raw = rec.get("raw") if hasattr(rec, "get") else None
        return parse_p90_degree_by_label(raw, label)
    except Exception:
        return None


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
    """
    Composite risk score (0-100) for a single entity, based on:
      - own tags
      - connection count
      - flagged neighbours
      - shared devices / attributes
      - community size

    Optional ``checkpoint`` selects a profile from ``checkpoint_profiles_v1.json`` (risk score multiplier).
    """
    from .checkpoint_registry import resolve_profile

    profile = resolve_profile(checkpoint)
    mult = float(profile.get("risk_score_multiplier") or 1.0)
    hop_depth = _clamp_depth(int(profile.get("max_neighbor_hops") or 3))

    driver = await get_driver()

    # Cypher requires path depth as a literal (not a parameter); keep bounded via checkpoint profile.
    q = f"""
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

    OPTIONAL MATCH (n)-[]-(nb)
    WHERE nb.tenant_id = $tenant_id AND nb.device_id IS NOT NULL
    WITH n, conn_count, flagged_neighbors, community_size, shared_device_count,
         count(DISTINCT nb.device_id) AS neighbor_device_count

    OPTIONAL MATCH (n)-[e]-()
    WITH n, conn_count, flagged_neighbors, community_size, shared_device_count, neighbor_device_count,
         coalesce(e.observed_at, e.created_at, e.updated_at) AS ts
    RETURN
      n.tags              AS tags,
      n.updated_at        AS updated_at,
      n.last_seen         AS last_seen,
      n.tags_updated_at   AS tags_updated_at,
      labels(n)[0]        AS primary_label,
      conn_count,
      flagged_neighbors,
      community_size,
      shared_device_count,
      neighbor_device_count,
      collect(ts) AS edge_timestamps
    """

    async with await _open_session(driver) as session:
        result = await session.run(
            q,
            tenant_id=tenant_id,
            entity_id=entity_id,
            high_risk_tags=sorted(_HIGH_RISK_TAGS),
        )
        rec = await result.single()

    if rec is None:
        return entity_not_found_payload(
            entity_id, checkpoint, profile.get("_profile_name"), hop_depth
        )

    tags = list(rec["tags"] or [])
    conn_count: int = rec["conn_count"]
    flagged: int = rec["flagged_neighbors"]
    community_size: int = rec["community_size"]
    shared_devices: int = rec["shared_device_count"]
    neighbor_device_count: int = int(rec.get("neighbor_device_count") or 0)
    relation_growth_1h, relation_growth_24h = _growth_from_record(rec)
    primary_label = rec.get("primary_label") or ""
    peer_p90 = (
        await load_peer_p90_for_label(tenant_id, str(primary_label)) if primary_label else None
    )

    from .graph_data_freshness import graph_data_as_of_iso

    freshness = graph_data_as_of_iso(
        {
            "updated_at": rec.get("updated_at"),
            "last_seen": rec.get("last_seen"),
            "tags_updated_at": rec.get("tags_updated_at"),
        }
    )

    return score_entity_risk(
        entity_id=entity_id,
        tags=tags,
        conn_count=conn_count,
        flagged=flagged,
        community_size=community_size,
        shared_devices=shared_devices,
        neighbor_device_count=neighbor_device_count,
        relation_growth_1h=relation_growth_1h,
        relation_growth_24h=relation_growth_24h,
        peer_p90=peer_p90,
        checkpoint=checkpoint,
        profile=profile.get("_profile_name"),
        hop_depth=hop_depth,
        freshness=freshness,
        multiplier=mult,
    )
