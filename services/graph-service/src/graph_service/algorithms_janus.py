from __future__ import annotations

import contextlib
import logging
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from typing import Any

import networkx as nx

from .config import settings
from .entity_risk_score import entity_not_found_payload, score_entity_risk
from .graph_data_freshness import _parse_timestamp
from .janusgraph_gremlin import get_traversal_source, run_in_gremlin_thread
from .janusgraph_store import _vertex_external_id

"""
Graph analytics when GRAPH_BACKEND=janusgraph (Gremlin).

Uses bounded traversals and in-memory helpers (union-find / optional NetworkX) so
operators can swap backends without changing Decision API, Case API, or copilot URLs.
Large tenants may hit ``janusgraph_analytics_vertex_cap`` — raise the cap or use Neo4j.
"""
log = logging.getLogger("graph-service.algorithms.janus")

_HIGH_RISK_TAGS = frozenset(
    {
        "fraud",
        "suspicious",
        "flagged",
        "blocked",
        "chargedback",
    },
)


def _clamp_depth(depth: int) -> int:
    return max(1, min(int(depth), 5))


def _coalesce_edge_ts(edge: Any) -> Any:
    for key in ("observed_at", "created_at", "updated_at"):
        with contextlib.suppress(Exception):
            val = edge.value(key)
            if val is not None and str(val).strip():
                return val
    return None


def _count_edge_growth(timestamps: list[Any]) -> tuple[int, int]:
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


async def load_peer_p90_for_label(tenant_id: str, label: str) -> int | None:
    try:
        from .graph_runtime import load_peer_p90_by_label

        return await load_peer_p90_by_label(tenant_id, label)
    except Exception:
        return None


def _tags_list_from_vertex(g, v: Any) -> list[str]:
    from .janusgraph_store import _tags_decode

    try:
        raw = g.V(v).values("tags").limit(1).next()
        return _tags_decode(raw)
    except StopIteration:
        return []


def _export_edges_sync(tenant_id: str) -> tuple[dict[Any, str], list[tuple[str, str]]]:
    """Map vertex id -> external_id for capped vertex set + undirected edge pairs."""
    cap = settings.janusgraph_analytics_vertex_cap
    g = get_traversal_source()
    vertices = g.V().has("tenant_id", tenant_id).limit(cap).toList()
    id_to_ext: dict[Any, str] = {}
    for v in vertices:
        eid = _vertex_external_id(v)
        if eid:
            id_to_ext[v.id] = eid
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for v in vertices:
        if v.id not in id_to_ext:
            continue
        for e in g.V(v).bothE().toList():
            a = e.outV().next()
            b = e.inV().next()
            ea, eb = id_to_ext.get(a.id), id_to_ext.get(b.id)
            if not ea or not eb or ea == eb:
                continue
            key = tuple(sorted((ea, eb)))
            if key in seen:
                continue
            seen.add(key)
            pairs.append((ea, eb))
    return id_to_ext, pairs


async def detect_communities(tenant_id: str, min_community_size: int = 3) -> list[dict]:
    def sync() -> list[dict]:
        id_to_ext, edges = _export_edges_sync(tenant_id)
        parent: dict[str, str] = {}

        def find(x: str) -> str:
            if x not in parent:
                parent[x] = x
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        for ext in set(id_to_ext.values()):
            find(ext)
        for a, b in edges:
            union(a, b)
        groups: dict[str, list[str]] = defaultdict(list)
        for x in parent:
            groups[find(x)].append(x)
        out: list[dict] = []
        idx = 0
        for _root, members in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            if len(members) < min_community_size:
                continue
            out.append(
                {
                    "community_id": idx,
                    "member_count": len(members),
                    "member_ids": sorted(members),
                    "member_labels": [],
                    "shared_attributes": [],
                },
            )
            idx += 1
        return out

    return await run_in_gremlin_thread(sync)


async def propagate_risk(
    tenant_id: str,
    entity_id: str,
    depth: int = 3,
    decay: float = 0.5,
) -> list[dict]:
    depth = _clamp_depth(depth)

    def sync() -> list[dict]:
        g = get_traversal_source()
        roots = g.V().has("tenant_id", tenant_id).has("external_id", entity_id).limit(1).toList()
        if not roots:
            return []
        root = roots[0]
        frontier: deque[Any] = deque([root])
        depth_map: dict[str, int] = {entity_id: 0}

        while frontier:
            v = frontier.popleft()
            ve = _vertex_external_id(v)
            d0 = depth_map.get(ve, 0)
            if d0 >= depth:
                continue
            for e in g.V(v).bothE().toList():
                other = e.inV().next() if e.outV().next().id == v.id else e.outV().next()
                oe = _vertex_external_id(other)
                if not oe or oe == entity_id:
                    continue
                try:
                    ot = other.value("tenant_id")
                except Exception:
                    continue
                if str(ot) != tenant_id:
                    continue
                if oe not in depth_map or depth_map[oe] > d0 + 1:
                    depth_map[oe] = d0 + 1
                    frontier.append(other)

        entities: list[dict] = []
        for eid, dist_i in sorted(depth_map.items(), key=lambda x: x[1]):
            if eid == entity_id:
                continue
            score = round(100.0 * (decay**dist_i), 2)
            entities.append(
                {
                    "entity_id": eid,
                    "entity_labels": [],
                    "propagated_risk_score": score,
                    "distance": dist_i,
                    "path_description": f"gremlin:bfs:{entity_id}->{eid}",
                    "node_chain": [entity_id, eid],
                    "rel_types": [],
                },
            )
        return entities

    return await run_in_gremlin_thread(sync)


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


async def find_shared_attributes(
    tenant_id: str,
    attribute: str = "device_id",
    min_shared: int = 2,
) -> list[dict]:
    import re

    if not re.match(r"^[A-Za-z][A-Za-z0-9_]{0,63}$", attribute):
        raise ValueError(f"Invalid attribute name: {attribute!r}")

    cap = settings.janusgraph_analytics_vertex_cap

    def sync() -> list[dict]:
        g = get_traversal_source()
        buckets: dict[str, list[str]] = defaultdict(list)
        for v in g.V().has("tenant_id", tenant_id).limit(cap).toList():
            eid = _vertex_external_id(v)
            if not eid:
                continue
            try:
                val = v.value(attribute)
            except Exception:
                continue
            if val is None:
                continue
            buckets[str(val)].append(eid)
        return [
            {
                "attribute": attribute,
                "shared_value": val,
                "entity_ids": eids,
                "group_size": len(eids),
            }
            for val, eids in sorted(buckets.items(), key=lambda kv: -len(kv[1]))
            if len(eids) >= min_shared
        ]

    return await run_in_gremlin_thread(sync)


async def detect_fraud_rings(tenant_id: str, min_ring_size: int = 3) -> list[dict]:
    min_ring_size = max(3, min(min_ring_size, 6))

    def sync() -> list[dict]:
        _, pairs = _export_edges_sync(tenant_id)
        G = nx.Graph()
        for a, b in pairs:
            G.add_edge(a, b)
        rings: list[dict] = []
        seen: set[str] = set()
        # cycle_basis is a tractable approximation (not every simple cycle); see adapter docs.
        for cycle in nx.cycle_basis(G):
            if len(cycle) < min_ring_size or len(cycle) > 6:
                continue
            canon = "|".join(sorted(cycle))
            if canon in seen:
                continue
            seen.add(canon)
            rings.append(
                {
                    "ring_members": cycle,
                    "ring_size": len(cycle),
                    "relationships": ["RELATED"] * len(cycle),
                    "aggregate_tags": [],
                },
            )
            if len(rings) >= 50:
                break
        return rings

    return await run_in_gremlin_thread(sync)


async def compute_entity_risk(
    tenant_id: str, entity_id: str, *, checkpoint: str | None = None
) -> dict:
    from .checkpoint_registry import resolve_profile

    profile = resolve_profile(checkpoint)
    mult = float(profile.get("risk_score_multiplier") or 1.0)
    hop_cap = max(1, min(int(profile.get("max_neighbor_hops") or 3), 5))

    def sync() -> dict:
        g = get_traversal_source()
        vl = g.V().has("tenant_id", tenant_id).has("external_id", entity_id).limit(1).toList()
        if not vl:
            return entity_not_found_payload(
                entity_id, checkpoint, profile.get("_profile_name"), hop_cap
            )
        v = vl[0]
        tags = _tags_list_from_vertex(g, v)
        neighbors: list[Any] = []
        edge_timestamps: list[Any] = []
        for e in g.V(v).bothE().toList():
            ts = _coalesce_edge_ts(e)
            if ts is not None:
                edge_timestamps.append(ts)
            other = e.inV().next() if e.outV().next().id == v.id else e.outV().next()
            try:
                if str(other.value("tenant_id")) != tenant_id:
                    continue
            except Exception:
                continue
            neighbors.append(other)

        relation_growth_1h, relation_growth_24h = _count_edge_growth(edge_timestamps)
        primary_label = ""
        with contextlib.suppress(Exception):
            primary_label = str(g.V(v).label().next()) or ""

        flagged = 0
        for nb in neighbors:
            ntags = {t.lower() for t in _tags_list_from_vertex(g, nb)}
            if ntags & {x.lower() for x in _HIGH_RISK_TAGS}:
                flagged += 1

        conn_count = len(neighbors)
        neighbor_device_ids: set[str] = set()
        for nb in neighbors:
            with contextlib.suppress(Exception):
                did = nb.value("device_id")
                if did is not None and str(did).strip():
                    neighbor_device_ids.add(str(did).strip())
        neighbor_device_count = len(neighbor_device_ids)
        device_id = None
        with contextlib.suppress(Exception):
            device_id = v.value("device_id")

        shared_devices = 0
        if device_id is not None:
            cap = settings.janusgraph_analytics_vertex_cap
            oids: set[str] = set()
            for ov in (
                g.V().has("tenant_id", tenant_id).has("device_id", device_id).limit(cap).toList()
            ):
                oid = _vertex_external_id(ov)
                if oid and oid != entity_id:
                    oids.add(oid)
            shared_devices = len(oids)

        # Bounded community size: BFS up to checkpoint max_neighbor_hops (1–5)
        hop_depth = hop_cap
        seen_bfs: set[str] = {entity_id}
        frontier = [v]
        for _ in range(hop_depth):
            nxt: list[Any] = []
            for x in frontier:
                for e in g.V(x).bothE().toList():
                    o = e.inV().next() if e.outV().next().id == x.id else e.outV().next()
                    oe = _vertex_external_id(o)
                    if oe and oe not in seen_bfs:
                        try:
                            if str(o.value("tenant_id")) == tenant_id:
                                seen_bfs.add(oe)
                                nxt.append(o)
                        except Exception:
                            pass
            frontier = nxt
        community_size = len(seen_bfs)

        from .graph_data_freshness import graph_data_as_of_iso

        freshness_props: dict[str, Any] = {}
        for key in ("updated_at", "last_seen", "tags_updated_at", "observed_at"):
            with contextlib.suppress(Exception):
                freshness_props[key] = v.value(key)
        freshness = graph_data_as_of_iso(freshness_props)

        return {
            "tags": tags,
            "conn_count": conn_count,
            "flagged": flagged,
            "community_size": community_size,
            "shared_devices": shared_devices,
            "neighbor_device_count": neighbor_device_count,
            "relation_growth_1h": relation_growth_1h,
            "relation_growth_24h": relation_growth_24h,
            "primary_label": primary_label,
            "hop_depth": hop_depth,
            "freshness": freshness,
        }

    data = await run_in_gremlin_thread(sync)
    if "conn_count" not in data:
        return data
    primary_label = str(data.get("primary_label") or "")
    peer_p90 = await load_peer_p90_for_label(tenant_id, primary_label) if primary_label else None
    return score_entity_risk(
        entity_id=entity_id,
        tags=data["tags"],
        conn_count=data["conn_count"],
        flagged=data["flagged"],
        community_size=data["community_size"],
        shared_devices=data["shared_devices"],
        neighbor_device_count=data["neighbor_device_count"],
        relation_growth_1h=data["relation_growth_1h"],
        relation_growth_24h=data["relation_growth_24h"],
        peer_p90=peer_p90,
        checkpoint=checkpoint,
        profile=profile.get("_profile_name"),
        hop_depth=data["hop_depth"],
        freshness=data["freshness"],
        multiplier=mult,
    )
