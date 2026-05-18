from __future__ import annotations

import logging
from collections import defaultdict, deque
from typing import Any

import networkx as nx

from graph_service.config import settings
from graph_service.janusgraph_gremlin import get_traversal_source, run_in_gremlin_thread
from graph_service.janusgraph_store import _vertex_external_id

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


def _tags_list_from_vertex(g, v: Any) -> list[str]:
    from graph_service.janusgraph_store import _tags_decode

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
                },
            )
        return entities

    return await run_in_gremlin_thread(sync)


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
    from graph_service.checkpoint_registry import resolve_profile

    profile = resolve_profile(checkpoint)
    mult = float(profile.get("risk_score_multiplier") or 1.0)
    hop_cap = max(1, min(int(profile.get("max_neighbor_hops") or 3), 5))

    def sync() -> dict:
        g = get_traversal_source()
        vl = g.V().has("tenant_id", tenant_id).has("external_id", entity_id).limit(1).toList()
        if not vl:
            return {
                "entity_id": entity_id,
                "risk_score": 0,
                "risk_factors": ["entity_not_found"],
                "connected_flagged_count": 0,
                "community_size": 0,
                "graph_checkpoint": checkpoint,
                "graph_profile": profile.get("_profile_name"),
                "graph_profile_max_neighbor_hops": hop_cap,
            }
        v = vl[0]
        tags = _tags_list_from_vertex(g, v)
        neighbors: list[Any] = []
        for e in g.V(v).bothE().toList():
            other = e.inV().next() if e.outV().next().id == v.id else e.outV().next()
            try:
                if str(other.value("tenant_id")) != tenant_id:
                    continue
            except Exception:
                continue
            neighbors.append(other)

        flagged = 0
        for nb in neighbors:
            ntags = set(t.lower() for t in _tags_list_from_vertex(g, nb))
            if ntags & {x.lower() for x in _HIGH_RISK_TAGS}:
                flagged += 1

        conn_count = len(neighbors)
        device_id = None
        try:
            device_id = v.value("device_id")
        except Exception:
            pass

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

        score = 0.0
        factors: list[str] = []
        own_risky = _HIGH_RISK_TAGS & {t.lower() for t in tags}
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

        return {
            "entity_id": entity_id,
            "risk_score": min(round(score * mult), 100),
            "risk_factors": factors,
            "connected_flagged_count": flagged,
            "community_size": community_size,
            "graph_checkpoint": checkpoint,
            "graph_profile": profile.get("_profile_name"),
            "graph_profile_multiplier": mult,
            "graph_profile_max_neighbor_hops": hop_depth,
        }

    return await run_in_gremlin_thread(sync)
