from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from typing import Any

from .growth_policy import threshold_for

FAST_GROWTH_1H = threshold_for("1h")
FAST_GROWTH_24H = threshold_for("24h")
_HIGH_RISK_TAGS = frozenset({"fraud", "suspicious", "flagged", "blocked", "chargedback"})


def link_props_for_create(properties: dict[str, Any] | None) -> dict[str, Any]:
    """Stamp observed_at=now when omitted. Use for ON CREATE / Janus addE (new edges)."""
    props = dict(properties or {})
    if "observed_at" not in props:
        props["observed_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return props


def link_props_for_match(properties: dict[str, Any] | None) -> dict[str, Any]:
    """Caller-supplied props only. Do not inject observed_at on MERGE match."""
    return dict(properties or {})


def _link_properties_with_observed_at(properties: dict[str, Any] | None) -> dict[str, Any]:
    return link_props_for_create(properties)


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
        "named_edges": [],
        "multi_id_user_ids": [],
        "roles": [],
    }


def is_found_payload(payload: dict[str, Any]) -> bool:
    factors = payload.get("risk_factors") or []
    return "entity_not_found" not in [str(x) for x in factors]


def _risk_factors_list(raw: Any) -> list:
    if raw is None:
        return []
    if isinstance(raw, list):
        return list(raw)
    if isinstance(raw, str):
        try:
            val = json.loads(raw)
            return list(val) if isinstance(val, list) else []
        except (TypeError, ValueError, json.JSONDecodeError):
            return [raw] if raw else []
    return [raw]


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
        "risk_factors": _risk_factors_list(p.get("risk_factors")),
        "relation_count": _num("relation_count"),
        "relation_growth_1h": _num("relation_growth_1h"),
        "relation_growth_24h": _num("relation_growth_24h"),
    }


def decorate_subgraph_node(node: dict[str, Any]) -> dict[str, Any]:
    props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    view = stored_risk_view(props)
    return {**node, **view}


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
    primary_label: str | None = None,
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
    if FAST_GROWTH_1H is not None and relation_growth_1h >= FAST_GROWTH_1H:
        score += 20
        factors.append(f"fast_growth_1h:{relation_growth_1h}")
    if FAST_GROWTH_24H is not None and relation_growth_24h >= FAST_GROWTH_24H:
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
        "primary_label": str(primary_label or ""),
        "named_edges": [],
        "multi_id_user_ids": [],
        "roles": [],
    }
    if freshness:
        out["graph_data_as_of"] = freshness
    return out


def clamp_search_limit(limit: int | None) -> int:
    if limit is None:
        return 20
    try:
        n = int(limit)
    except (TypeError, ValueError):
        return 20
    return max(1, min(50, n))


SEARCH_PROP_KEYS = (
    "external_id",
    "email",
    "device_id",
    "address",
    "line1",
    "phone",
    "ip",
    "user_id",
    "card_id",
)
IDENTIFIER_LABELS = frozenset({"Email", "Device", "IP", "Phone", "Address", "Card"})
OWNER_LABELS = frozenset({"Person", "Account", "User", "user"})
SEARCH_OWNER_FANOUT = 10


def matched_on_from_props(props: dict[str, Any] | None, q: str) -> str | None:
    needle = str(q or "").casefold()
    if not needle:
        return None
    bag = props or {}
    for key in SEARCH_PROP_KEYS:
        val = bag.get(key)
        if isinstance(val, str) and needle in val.casefold():
            return key
    return None


def matched_on_from_props_prefix(props: dict[str, Any] | None, q: str) -> str | None:
    needle = str(q or "").casefold()
    if not needle:
        return None
    bag = props or {}
    for key in SEARCH_PROP_KEYS:
        val = bag.get(key)
        if isinstance(val, str) and val.casefold().startswith(needle):
            return key
    return None


def eligible_search_node_prefix(entity_id: str, props: dict[str, Any] | None, q: str) -> str | None:
    eid = str(entity_id or "").strip()
    if not eid:
        return None
    bag = dict(props or {})
    bag.setdefault("external_id", eid)
    return matched_on_from_props_prefix(bag, q)


def eligible_search_node(entity_id: str, props: dict[str, Any] | None, q: str) -> str | None:
    eid = str(entity_id or "").strip()
    if not eid:
        return None
    bag = dict(props or {})
    bag.setdefault("external_id", eid)
    return matched_on_from_props(bag, q)


def labels_are_identifier(labels: list) -> bool:
    return bool(IDENTIFIER_LABELS.intersection(str(x) for x in (labels or [])))


def labels_are_owner(labels: list) -> bool:
    return bool(OWNER_LABELS.intersection(str(x) for x in (labels or [])))


def cypher_search_prop_predicate(alias: str = "n") -> str:
    # ponytail: interpolates frozen SEARCH_PROP_KEYS only; $q stays parameterized.
    parts: list[str] = []
    for key in SEARCH_PROP_KEYS:
        parts.append(
            f"({alias}.{key} IS NOT NULL AND {alias}.{key} = toString({alias}.{key}) "
            f"AND toLower({alias}.{key}) CONTAINS toLower($q))"
        )
    return " OR ".join(parts)


def _prop_rank(key: str) -> int:
    try:
        return SEARCH_PROP_KEYS.index(key)
    except ValueError:
        return len(SEARCH_PROP_KEYS)


def cap_identifier_owners(
    hits: list[dict[str, Any]], fanout: int = SEARCH_OWNER_FANOUT
) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for hit in hits:
        via = hit.get("via") or {}
        via_id = str(via.get("entity_id") or "")
        oid = str(hit.get("entity_id") or "")
        pair = (via_id, oid)
        if pair in seen:
            continue
        seen.add(pair)
        n = counts.get(via_id, 0)
        if n >= fanout:
            continue
        counts[via_id] = n + 1
        out.append(hit)
    return out


def _prefer_search_hit(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    a_owner = labels_are_owner(a.get("labels") or [])
    b_owner = labels_are_owner(b.get("labels") or [])
    if b_owner and not a_owner:
        base, other = b, a
    else:
        base, other = a, b
    out = dict(base)
    out["via"] = base.get("via") or other.get("via")
    ma = str(base.get("matched_on") or "")
    mb = str(other.get("matched_on") or "")
    out["matched_on"] = ma if _prop_rank(ma) <= _prop_rank(mb) else mb
    return out


def merge_search_hits(
    hits: list[dict[str, Any]],
    *,
    label: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for hit in hits:
        eid = str(hit.get("entity_id") or "")
        if not eid:
            continue
        prev = by_id.get(eid)
        by_id[eid] = hit if prev is None else _prefer_search_hit(prev, hit)
    rows = list(by_id.values())
    if label:
        rows = [h for h in rows if label in [str(x) for x in (h.get("labels") or [])]]

    def sort_key(h: dict[str, Any]) -> tuple:
        owner = labels_are_owner(h.get("labels") or [])
        scored = bool(h.get("scored"))
        risk = h.get("risk_score")
        risk_sort = -float(risk) if scored and isinstance(risk, (int, float)) else 0.0
        return (not owner, 0 if scored else 1, risk_sort, str(h.get("entity_id") or ""))

    rows.sort(key=sort_key)
    return rows[: int(limit)]


def search_hit_from_node(
    tenant_id: str,
    entity_id: str,
    labels: list,
    props: dict[str, Any] | None,
    *,
    matched_on: str = "external_id",
    via: dict[str, Any] | None = None,
) -> dict[str, Any]:
    view = stored_risk_view(props)
    labs = [str(x) for x in (labels or [])]
    return {
        "entity_id": str(entity_id),
        "tenant_id": str(tenant_id),
        "labels": labs,
        "scored": bool(view["scored"]),
        "risk_score": view["risk_score"],
        "matched_on": matched_on,
        "via": via,
    }
