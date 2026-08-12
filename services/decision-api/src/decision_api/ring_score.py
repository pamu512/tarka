"""Multi-party ring score — structural collusion depth engine (no LIVE / no GNN claim).

Consumes a role-labeled party graph from the host (or graph-service dump).
LIVE device vendors later substitute richer USES_DEVICE / SEEN_AT edges into the
same schema; scoring method stays heuristic_v1 until a labeled GNN path is proven.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

SCHEMA_ID = "tarka.ring_score/v1"
METHOD = "heuristic_v1"

_STALE_EDGE_HOURS = 72.0
_FRESH_EDGE_HOURS = 1.0

_PERSON_ROLES = frozenset(
    {"buyer", "seller", "courier", "driver", "rider", "diner", "merchant", "worker"}
)
_BRIDGE_ROLES = frozenset({"device", "place", "promo", "payment_instrument"})
_CROSS_ROLE_GROUPS = (
    frozenset({"buyer", "seller"}),
    frozenset({"buyer", "courier"}),
    frozenset({"diner", "courier"}),
    frozenset({"diner", "merchant"}),
    frozenset({"rider", "driver"}),
    frozenset({"buyer", "driver"}),
)


@dataclass
class RingFactor:
    code: str
    weight: float
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "weight": round(self.weight, 2),
            "detail": self.detail,
        }


@dataclass
class RingScoreResult:
    score_0_100: float
    factors: list[RingFactor] = field(default_factory=list)
    cross_role_same_device: bool = False
    component_size: int = 0
    members: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    components: int = 0

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_id": SCHEMA_ID,
            "score_0_100": round(self.score_0_100, 2),
            "cross_role_same_device": self.cross_role_same_device,
            "component_size": self.component_size,
            "components": self.components,
            "members": list(self.members)[:64],
            "factors": [f.as_dict() for f in self.factors],
            "tags": list(self.tags),
            "method": METHOD,
            "gnn_claim_allowed": False,
            "live_amplification": (
                "Replace host USES_DEVICE/SEEN_AT edges with Fingerprint/Incognia/"
                "SHIELD writebacks; keep heuristic_v1 until labeled GNN proven."
            ),
        }


class _UF:
    def __init__(self) -> None:
        self.p: dict[str, str] = {}
        self.r: dict[str, int] = {}

    def add(self, x: str) -> None:
        if x not in self.p:
            self.p[x] = x
            self.r[x] = 0

    def find(self, x: str) -> str:
        self.add(x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.r[ra] < self.r[rb]:
            ra, rb = rb, ra
        self.p[rb] = ra
        if self.r[ra] == self.r[rb]:
            self.r[ra] += 1

    def components(self) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        for x in self.p:
            root = self.find(x)
            groups.setdefault(root, []).append(x)
        return groups


def _extract_graph(
    payload: dict[str, Any] | None, metadata: dict[str, Any] | None
) -> dict[str, Any] | None:
    for src in (metadata, payload):
        if not isinstance(src, dict):
            continue
        g = src.get("party_graph") or src.get("ring_graph")
        if isinstance(g, dict) and (
            isinstance(g.get("nodes"), list) or isinstance(g.get("edges"), list)
        ):
            return g
    return None


def _norm_nodes(raw: list[Any]) -> dict[str, dict[str, Any]]:
    nodes: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        nid = str(item.get("id") or item.get("node_id") or "").strip()
        if not nid:
            continue
        role = str(item.get("role") or item.get("type") or "unknown").strip().lower()
        attrs = item.get("attrs") if isinstance(item.get("attrs"), dict) else {}
        nodes[nid] = {"id": nid, "role": role, "attrs": attrs}
    return nodes


def _parse_ts(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(raw, str) and raw.strip():
        s = raw.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _norm_edges(raw: list[Any]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        src = str(
            item.get("src") or item.get("from") or item.get("source") or ""
        ).strip()
        dst = str(item.get("dst") or item.get("to") or item.get("target") or "").strip()
        if not src or not dst:
            continue
        etype = (
            str(item.get("type") or item.get("edge_type") or "RELATED").strip().upper()
        )
        try:
            weight = float(
                item.get("weight") if item.get("weight") is not None else 1.0
            )
        except (TypeError, ValueError):
            weight = 1.0
        try:
            count_24h = int(item.get("count_24h") or item.get("count") or 0)
        except (TypeError, ValueError):
            count_24h = 0
        ts = _parse_ts(item.get("ts") or item.get("observed_at") or item.get("at"))
        age_hours = None
        if item.get("age_hours") is not None:
            try:
                age_hours = max(0.0, float(item["age_hours"]))
            except (TypeError, ValueError):
                age_hours = None
        edges.append(
            {
                "src": src,
                "dst": dst,
                "type": etype,
                "weight": weight,
                "count_24h": max(0, count_24h),
                "ts": ts,
                "age_hours": age_hours,
            }
        )
    return edges


def _edge_age_hours(edge: dict[str, Any], as_of: datetime) -> float | None:
    if edge.get("age_hours") is not None:
        return float(edge["age_hours"])
    ts = edge.get("ts")
    if isinstance(ts, datetime):
        return max(0.0, (as_of - ts).total_seconds() / 3600.0)
    return None


def _resolve_as_of(edges: list[dict[str, Any]], graph: dict[str, Any]) -> datetime:
    raw = graph.get("as_of") or graph.get("observed_at")
    parsed = _parse_ts(raw)
    if parsed:
        return parsed
    stamped = [e["ts"] for e in edges if isinstance(e.get("ts"), datetime)]
    if stamped:
        return max(stamped)
    return datetime.now(timezone.utc)


def _bridge_person_count(
    bridge_id: str,
    member_set: set[str],
    nodes: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
) -> int:
    persons: set[str] = set()
    for e in edges:
        other = None
        if e["src"] == bridge_id and e["dst"] in member_set:
            other = e["dst"]
        elif e["dst"] == bridge_id and e["src"] in member_set:
            other = e["src"]
        if other and nodes.get(other, {}).get("role") in _PERSON_ROLES:
            persons.add(other)
    return len(persons)


def _ensure_edge_nodes(
    nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]
) -> None:
    for e in edges:
        for endpoint in (e["src"], e["dst"]):
            if endpoint not in nodes:
                # Infer role from id prefix heuristics; else unknown
                role = "unknown"
                low = endpoint.lower()
                if low.startswith("dev") or "device" in low:
                    role = "device"
                elif low.startswith("plc") or "place" in low:
                    role = "place"
                nodes[endpoint] = {"id": endpoint, "role": role, "attrs": {}}


def _add(factors: list[RingFactor], code: str, weight: float, detail: str) -> None:
    if weight <= 0:
        return
    factors.append(
        RingFactor(code=code, weight=min(40.0, float(weight)), detail=detail)
    )


def _roles_in_component(
    members: list[str], nodes: dict[str, dict[str, Any]]
) -> set[str]:
    return {nodes[m]["role"] for m in members if m in nodes}


def _device_bridges(
    members: list[str],
    nodes: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[tuple[str, set[str]]]:
    """For each device/place in component, person-roles attached."""
    member_set = set(members)
    adj: dict[str, set[str]] = {m: set() for m in members}
    for e in edges:
        if e["src"] in member_set and e["dst"] in member_set:
            adj[e["src"]].add(e["dst"])
            adj[e["dst"]].add(e["src"])
    out: list[tuple[str, set[str]]] = []
    for m in members:
        role = nodes[m]["role"]
        if role not in _BRIDGE_ROLES:
            continue
        person_roles: set[str] = set()
        for nb in adj.get(m, set()):
            r = nodes[nb]["role"]
            if r in _PERSON_ROLES:
                person_roles.add(r)
        if person_roles:
            out.append((m, person_roles))
    return out


def compute_ring_score(
    *,
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> RingScoreResult | None:
    g = _extract_graph(payload, metadata)
    if g is None:
        return None
    nodes = _norm_nodes(list(g.get("nodes") or []))
    edges = _norm_edges(list(g.get("edges") or []))
    if not edges and len(nodes) < 2:
        return None
    _ensure_edge_nodes(nodes, edges)
    if not nodes:
        return None

    uf = _UF()
    for nid in nodes:
        uf.add(nid)
    for e in edges:
        # Bridge edges always connect; person-person TRANSACTED also connects
        uf.union(e["src"], e["dst"])

    comps = uf.components()
    # Focus on largest multi-node component
    ranked = sorted(comps.values(), key=len, reverse=True)
    primary = next((c for c in ranked if len(c) >= 2), ranked[0] if ranked else [])
    if not primary:
        return None

    factors: list[RingFactor] = []
    cross_role = False
    as_of = _resolve_as_of(edges, g)
    member_set = set(primary)

    # Temporal edge ages (structure depth C)
    ages = [
        a
        for e in edges
        if e["src"] in member_set and e["dst"] in member_set
        for a in [_edge_age_hours(e, as_of)]
        if a is not None
    ]
    fresh_n = sum(1 for a in ages if a <= _FRESH_EDGE_HOURS)
    stale_n = sum(1 for a in ages if a >= _STALE_EDGE_HOURS)
    stale_ratio = (stale_n / len(ages)) if ages else 0.0
    velocity_mul = 0.45 if stale_ratio >= 0.7 else (0.7 if stale_ratio >= 0.4 else 1.0)

    bridges = _device_bridges(primary, nodes, edges)
    for bridge_id, person_roles in bridges:
        b_role = nodes[bridge_id]["role"]
        for group in _CROSS_ROLE_GROUPS:
            if len(person_roles & group) >= 2:
                cross_role = True
                if b_role == "payment_instrument":
                    code, w = "cross_role_payment", 32.0
                elif b_role == "place":
                    code, w = "cross_role_place", 30.0
                else:
                    code, w = "cross_role_device", 34.0
                _add(
                    factors,
                    code,
                    w,
                    f"{b_role} bridge {bridge_id[:40]} links roles {sorted(person_roles)}",
                )
                break
        if len(person_roles) >= 3:
            hub_code = (
                "multi_role_hub_payment"
                if b_role == "payment_instrument"
                else (
                    "multi_role_hub_place"
                    if b_role == "place"
                    else "multi_role_hub_device"
                )
            )
            _add(
                factors,
                hub_code,
                20,
                f"Bridge {bridge_id[:40]} spans {len(person_roles)} person roles",
            )
        # Degree hubs (many distinct persons on place/payment)
        if b_role in ("place", "payment_instrument"):
            pcount = _bridge_person_count(bridge_id, member_set, nodes, edges)
            if b_role == "place" and pcount >= 4:
                _add(
                    factors,
                    "place_hub",
                    18,
                    f"Place {bridge_id[:32]} linked to {pcount} persons",
                )
            if b_role == "payment_instrument" and pcount >= 4:
                _add(
                    factors,
                    "payment_hub",
                    20,
                    f"Payment instrument {bridge_id[:32]} linked to {pcount} persons",
                )

    # Pair / trip velocity on person-person edges inside component
    for e in edges:
        if e["src"] not in member_set or e["dst"] not in member_set:
            continue
        r1, r2 = nodes[e["src"]]["role"], nodes[e["dst"]]["role"]
        if r1 in _PERSON_ROLES and r2 in _PERSON_ROLES and e["count_24h"] >= 6:
            complementary = any(
                r1 in grp and r2 in grp for grp in _CROSS_ROLE_GROUPS
            ) or (r1 != r2)
            if complementary:
                w = 22.0 if e["count_24h"] >= 10 else 14.0
                w *= velocity_mul
                _add(
                    factors,
                    "pair_velocity",
                    w,
                    f"{e['src'][:20]}↔{e['dst'][:20]} count_24h={e['count_24h']}"
                    + (f" stale_mul={velocity_mul:.2f}" if velocity_mul < 1.0 else ""),
                )

    if fresh_n >= 3 and len(ages) >= 3:
        _add(
            factors,
            "fresh_edge_burst",
            14,
            f"{fresh_n} edges observed within {_FRESH_EDGE_HOURS:.0f}h",
        )
    if stale_ratio >= 0.7 and len(ages) >= 3:
        _add(
            factors,
            "stale_edge_dominance",
            8,
            f"{stale_ratio:.0%} edges older than {_STALE_EDGE_HOURS:.0f}h (velocity decayed)",
        )

    # Promo hub: promo node linked to many buyers
    for nid, n in nodes.items():
        if n["role"] != "promo" or nid not in member_set:
            continue
        buyers = 0
        for e in edges:
            other = None
            if e["src"] == nid:
                other = e["dst"]
            elif e["dst"] == nid:
                other = e["src"]
            if other and nodes.get(other, {}).get("role") in (
                "buyer",
                "diner",
                "rider",
            ):
                buyers += 1
        if buyers >= 5:
            _add(
                factors,
                "promo_hub",
                18,
                f"Promo {nid[:32]} linked to {buyers} consumer roles",
            )

    # Promo → device → complementary roles chain
    for nid, n in nodes.items():
        if n["role"] != "promo" or nid not in member_set:
            continue
        # neighbors of promo
        promo_nbs = set()
        for e in edges:
            if e["src"] == nid and e["dst"] in member_set:
                promo_nbs.add(e["dst"])
            elif e["dst"] == nid and e["src"] in member_set:
                promo_nbs.add(e["src"])
        for nb in promo_nbs:
            if nodes[nb]["role"] != "device":
                continue
            # roles on that device
            roles_on_dev: set[str] = set()
            for e in edges:
                other = None
                if e["src"] == nb and e["dst"] in member_set:
                    other = e["dst"]
                elif e["dst"] == nb and e["src"] in member_set:
                    other = e["src"]
                if other and nodes.get(other, {}).get("role") in _PERSON_ROLES:
                    roles_on_dev.add(nodes[other]["role"])
            if any(len(roles_on_dev & grp) >= 2 for grp in _CROSS_ROLE_GROUPS):
                _add(
                    factors,
                    "promo_device_role_chain",
                    22,
                    f"Promo {nid[:24]}→device {nb[:24]}→roles {sorted(roles_on_dev)}",
                )
                cross_role = True
                break

    # Component size pressure
    if len(primary) >= 8:
        _add(factors, "large_ring", 12, f"Component size {len(primary)}")
    elif len(primary) >= 5:
        _add(factors, "medium_ring", 6, f"Component size {len(primary)}")

    # Bipartite density: fraction of cross-group edges among person nodes
    persons = [m for m in primary if nodes[m]["role"] in _PERSON_ROLES]
    if len(persons) >= 2:
        cross_edges = 0
        possible = 0
        for e in edges:
            if e["src"] not in member_set or e["dst"] not in member_set:
                continue
            r1, r2 = nodes[e["src"]]["role"], nodes[e["dst"]]["role"]
            if r1 not in _PERSON_ROLES or r2 not in _PERSON_ROLES:
                continue
            possible += 1
            if r1 != r2 and any(r1 in g and r2 in g for g in _CROSS_ROLE_GROUPS):
                cross_edges += 1
        if possible >= 3 and cross_edges / possible >= 0.6:
            _add(
                factors,
                "bipartite_density",
                16,
                f"Cross-role edge density {cross_edges}/{possible}",
            )

    # Node attrs: worker_auth_failed / account_rental hints
    for m in primary:
        attrs = nodes[m].get("attrs") or {}
        if attrs.get("worker_auth_failed") is True:
            _add(factors, "worker_auth_failed", 28, f"Node {m[:32]} failed worker auth")
        if attrs.get("account_age_days") is not None:
            try:
                age = float(attrs["account_age_days"])
                if age <= 7 and nodes[m]["role"] in _PERSON_ROLES:
                    # only if also in a multi-node ring with velocity
                    if any(f.code == "pair_velocity" for f in factors):
                        _add(
                            factors,
                            "young_account_in_ring",
                            10,
                            f"Young account {m[:32]} age_days={age}",
                        )
            except (TypeError, ValueError):
                pass

    raw = sum(f.weight for f in factors)
    score = max(0.0, min(100.0, raw))
    tags: list[str] = []
    if factors:
        tags.append("risk:collusion_shared_device")
    if cross_role:
        tags.append("action:hard_challenge")
        tags.append("risk:cross_role_device")
    if any(f.code == "cross_role_payment" for f in factors):
        tags.append("risk:shared_payment_instrument")
    if any(f.code in ("place_hub", "cross_role_place") for f in factors):
        tags.append("risk:place_hub")
    if any(f.code == "pair_velocity" for f in factors):
        tags.append("risk:collusion_pair_velocity")
    if any(f.code in ("promo_hub", "promo_device_role_chain") for f in factors):
        tags.append("risk:promo_farm")
    if any(f.code == "fresh_edge_burst" for f in factors):
        tags.append("risk:ring_edge_burst")
    if any(f.code == "worker_auth_failed" for f in factors):
        tags.append("risk:account_rental")
        tags.append("action:suspend_driving")
    if score >= 70:
        tags.append("action:hard_challenge")

    return RingScoreResult(
        score_0_100=score,
        factors=factors,
        cross_role_same_device=cross_role,
        component_size=len(primary),
        members=sorted(primary),
        tags=list(dict.fromkeys(tags)),
        components=len([c for c in ranked if len(c) >= 2]),
    )


def apply_ring_score_features(
    features: dict[str, Any],
    payload: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any] | None:
    result = compute_ring_score(payload=payload, metadata=metadata)
    if result is None:
        return None
    features["ring_score"] = round(result.score_0_100, 2)
    _critical = {
        "cross_role_device",
        "cross_role_payment",
        "cross_role_place",
        "multi_role_hub_device",
        "multi_role_hub_payment",
        "pair_velocity",
        "worker_auth_failed",
        "bipartite_density",
        "payment_hub",
        "place_hub",
        "promo_device_role_chain",
        "fresh_edge_burst",
    }
    features["ring_score_high"] = (
        result.score_0_100 >= 40.0
        or result.cross_role_same_device
        or any(f.code in _critical for f in result.factors)
    )
    features["cross_role_same_device"] = result.cross_role_same_device
    features["ring_component_size"] = result.component_size
    for f in result.factors:
        features[f"ring_factor:{f.code}"] = True
    return result.evidence()
