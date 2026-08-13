from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

FAST_GROWTH_1H = 5
FAST_GROWTH_24H = 15
_HIGH_RISK_TAGS = frozenset({"fraud", "suspicious", "flagged", "blocked", "chargedback"})


def _link_properties_with_observed_at(properties: dict[str, Any] | None) -> dict[str, Any]:
    props = dict(properties or {})
    if "observed_at" not in props:
        props["observed_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return props


def p90_degree(values: list[int]) -> int | None:
    if not values:
        return None
    xs = sorted(int(v) for v in values)
    idx = max(0, math.ceil(0.9 * len(xs)) - 1)
    return xs[idx]


def entity_not_found_payload(
    entity_id: str,
    checkpoint: str | None,
    profile: str | None,
    hop_depth: int,
) -> dict[str, Any]:
    return {
        "entity_id": entity_id,
        "risk_score": 0,
        "risk_factors": ["entity_not_found"],
        "connected_flagged_count": 0,
        "community_size": 0,
        "neighbor_device_count": 0,
        "graph_checkpoint": checkpoint,
        "graph_profile": profile,
        "graph_profile_max_neighbor_hops": hop_depth,
        "scored": False,
        "relation_count": 0,
        "relation_growth_1h": 0,
        "relation_growth_24h": 0,
    }


def is_found_payload(payload: dict[str, Any]) -> bool:
    factors = payload.get("risk_factors") or []
    return "entity_not_found" not in [str(x) for x in factors]


def stored_risk_view(props: dict[str, Any] | None) -> dict[str, Any]:
    p = props if isinstance(props, dict) else {}
    computed = p.get("risk_computed_at")
    if computed is None or str(computed).strip() == "":
        return {
            "scored": False,
            "risk_score": None,
            "risk_computed_at": None,
            "risk_factors": None,
            "relation_count": None,
            "relation_growth_1h": None,
            "relation_growth_24h": None,
        }

    def _num(key: str) -> float | int | None:
        try:
            return p[key]
        except KeyError:
            return None

    return {
        "scored": True,
        "risk_score": _num("risk_score"),
        "risk_computed_at": str(computed),
        "risk_factors": list(p.get("risk_factors") or []),
        "relation_count": _num("relation_count"),
        "relation_growth_1h": _num("relation_growth_1h"),
        "relation_growth_24h": _num("relation_growth_24h"),
    }


def score_entity_risk(
    *,
    entity_id: str,
    tags: list[str],
    conn_count: int,
    flagged: int,
    community_size: int,
    shared_devices: int,
    neighbor_device_count: int,
    relation_growth_1h: int,
    relation_growth_24h: int,
    peer_p90: int | None,
    checkpoint: str | None,
    profile: str | None,
    hop_depth: int,
    freshness: str | None,
    multiplier: float = 1.0,
) -> dict[str, Any]:
    score = 0.0
    factors: list[str] = []
    own_risky = _HIGH_RISK_TAGS & {str(t).lower() for t in tags}
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
    if peer_p90 is not None and conn_count >= max(10, int(peer_p90)):
        score += 15
        factors.append(f"high_degree_vs_peers:{conn_count}:p90={int(peer_p90)}")
    elif conn_count >= 10:
        score += 10
        factors.append(f"high_connectivity:{conn_count}")
    elif conn_count >= 5:
        score += 5
        factors.append(f"moderate_connectivity:{conn_count}")
    if relation_growth_1h >= FAST_GROWTH_1H:
        score += 20
        factors.append(f"fast_growth_1h:{relation_growth_1h}")
    if relation_growth_24h >= FAST_GROWTH_24H:
        score += 15
        factors.append(f"fast_growth_24h:{relation_growth_24h}")
    score = min(round(score * float(multiplier)), 100)
    out: dict[str, Any] = {
        "entity_id": entity_id,
        "risk_score": score,
        "risk_factors": factors,
        "connected_flagged_count": flagged,
        "community_size": community_size,
        "neighbor_device_count": neighbor_device_count,
        "graph_checkpoint": checkpoint,
        "graph_profile": profile,
        "graph_profile_multiplier": float(multiplier),
        "graph_profile_max_neighbor_hops": hop_depth,
        "scored": True,
        "relation_count": int(conn_count),
        "relation_growth_1h": int(relation_growth_1h),
        "relation_growth_24h": int(relation_growth_24h),
    }
    if freshness:
        out["graph_data_as_of"] = freshness
    return out
