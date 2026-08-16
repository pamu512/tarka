"""Pure graph-signal math. No TransactionSchema / Gremlin / Neo4j imports."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

IP_VELOCITY_SYBIL_THRESHOLD = 5
GRAPH_SIGNALS_IP_VELOCITY_WINDOW = timedelta(hours=2)
GRAPH_SIGNALS_TWO_HOP_CARD_WINDOW = timedelta(hours=2)
CLUSTERING_MIN_DEVICES = 3

LABEL_USER = "User"
LABEL_DEVICE = "Device"
LABEL_IP = "IP"
LABEL_CARD = "Card"

REL_USED_DEVICE = "USED_DEVICE"
REL_ORDERED_FROM_IP = "ORDERED_FROM_IP"
REL_PAID_WITH_CARD = "PAID_WITH_CARD"

LABEL_KEY = {
    LABEL_USER: "user_id",
    LABEL_IP: "address",
    LABEL_DEVICE: "device_id",
    LABEL_CARD: "card_id",
}

# Seed + 2 extra waves reaches User→IP←User→Card (and device-neighbor cards).
SIGNAL_HOP_EXTRA_WAVES = 2


def gremlin_scalar(value: Any) -> str:
    """TinkerPop ``values()`` often returns a list; callers need one id string."""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    if value is None:
        return ""
    return str(value).strip()


def collect_signal_hops(
    fetch_both_e: Callable[[str, str, str], Iterable[SignalHop]],
    seed_label: str,
    seed_id: str,
    *,
    extra_waves: int = SIGNAL_HOP_EXTRA_WAVES,
) -> list[SignalHop]:
    """Expand ``bothE`` from seed, then ``extra_waves`` neighbor rounds."""
    hops: list[SignalHop] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    expanded: set[tuple[str, str]] = set()
    frontier: list[tuple[str, str]] = [(seed_label, seed_id)]
    rounds = max(0, int(extra_waves)) + 1
    for _ in range(rounds):
        nxt: list[tuple[str, str]] = []
        for lab, nid in frontier:
            key = LABEL_KEY.get(lab)
            if not key or (lab, nid) in expanded:
                continue
            expanded.add((lab, nid))
            for hop in fetch_both_e(lab, key, nid):
                sig = (hop.src_label, hop.src_id, hop.rel, hop.dst_label, hop.dst_id)
                if sig in seen:
                    continue
                seen.add(sig)
                hops.append(hop)
                for olab, oid in ((hop.src_label, hop.src_id), (hop.dst_label, hop.dst_id)):
                    if (olab, oid) not in expanded and olab in LABEL_KEY:
                        nxt.append((olab, oid))
        frontier = nxt
    return hops


def device_hardware_risk_from_hops(
    device_id: str,
    hops: list[SignalHop],
    *,
    current_user_id: str | None = None,
) -> dict[str, Any]:
    """Reuse count is real. Blocked-user fields stay unimplemented on Gremlin."""
    users = _users_on_device(hops, device_id)
    if current_user_id:
        users.discard(current_user_id)
    return {
        "device_id": device_id,
        "linked_to_blocked_node": False,
        "blocked_user_count_on_device": 0,
        "users_on_device": len(users),
        "implemented": False,
        "status": "unavailable",
        "signals_usable": False,
        "backend": "janusgraph",
        "signals_note": "is_blocked not on Gremlin vertices; users_on_device is reuse count only",
    }


@dataclass(frozen=True, slots=True)
class SignalHop:
    """One directed relationship used for structural signals."""

    src_label: str
    src_id: str
    rel: str
    dst_label: str
    dst_id: str
    observed_at: datetime | None = None


def ip_velocity_block(
    *, distinct_users_last_2h: int, threshold: int = IP_VELOCITY_SYBIL_THRESHOLD
) -> dict[str, Any]:
    """Pure scoring for ``IP_VELOCITY``."""
    spike = distinct_users_last_2h > threshold
    denom = max(float(threshold), 1.0)
    score = min(float(distinct_users_last_2h) / denom, 10.0)
    return {
        "distinct_users_last_2h": distinct_users_last_2h,
        "threshold": threshold,
        "spike": spike,
        "score": score,
    }


def _aware(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts


def _in_window(obs: datetime | None, cutoff: datetime) -> bool:
    if obs is None:
        return False
    return _aware(obs) >= cutoff


def _other(hop: SignalHop, label: str, node_id: str) -> tuple[str, str] | None:
    if hop.src_label == label and hop.src_id == node_id:
        return hop.dst_label, hop.dst_id
    if hop.dst_label == label and hop.dst_id == node_id:
        return hop.src_label, hop.src_id
    return None


def _degree(hops: list[SignalHop], label: str, node_id: str) -> tuple[dict[str, int], int]:
    seen: set[tuple[str, str]] = set()
    for hop in hops:
        other = _other(hop, label, node_id)
        if other is None:
            continue
        seen.add(other)
    by: dict[str, int] = {}
    for olabel, _oid in seen:
        by[olabel] = by.get(olabel, 0) + 1
    return by, len(seen)


def _users_on_ip(hops: list[SignalHop], ip: str, cutoff: datetime) -> set[str]:
    users: set[str] = set()
    for hop in hops:
        if hop.rel != REL_ORDERED_FROM_IP or not _in_window(hop.observed_at, cutoff):
            continue
        other = _other(hop, LABEL_IP, ip)
        if other and other[0] == LABEL_USER:
            users.add(other[1])
    return users


def _ips_for_user(hops: list[SignalHop], user_id: str) -> set[str]:
    ips: set[str] = set()
    for hop in hops:
        if hop.rel != REL_ORDERED_FROM_IP:
            continue
        other = _other(hop, LABEL_USER, user_id)
        if other and other[0] == LABEL_IP:
            ips.add(other[1])
    return ips


def _devices_for_user(hops: list[SignalHop], user_id: str) -> list[str]:
    devices: list[str] = []
    seen: set[str] = set()
    for hop in hops:
        if hop.rel != REL_USED_DEVICE:
            continue
        other = _other(hop, LABEL_USER, user_id)
        if other and other[0] == LABEL_DEVICE and other[1] not in seen:
            seen.add(other[1])
            devices.append(other[1])
    return devices


def _users_on_device(hops: list[SignalHop], device_id: str) -> set[str]:
    users: set[str] = set()
    for hop in hops:
        if hop.rel != REL_USED_DEVICE:
            continue
        other = _other(hop, LABEL_DEVICE, device_id)
        if other and other[0] == LABEL_USER:
            users.add(other[1])
    return users


def _cards_for_user(hops: list[SignalHop], user_id: str, cutoff: datetime) -> set[str]:
    cards: set[str] = set()
    for hop in hops:
        if hop.rel != REL_PAID_WITH_CARD or not _in_window(hop.observed_at, cutoff):
            continue
        other = _other(hop, LABEL_USER, user_id)
        if other and other[0] == LABEL_CARD:
            cards.add(other[1])
    return cards


def _two_hop_cards_user(hops: list[SignalHop], user_id: str, cutoff: datetime) -> int:
    cards: set[str] = set()
    for ip in _ips_for_user(hops, user_id):
        for other in _users_on_ip(hops, ip, cutoff):
            if other == user_id:
                continue
            cards.update(_cards_for_user(hops, other, cutoff))
    return len(cards)


def _two_hop_cards_ip(hops: list[SignalHop], ip: str, cutoff: datetime) -> int:
    cards: set[str] = set()
    for user_id in _users_on_ip(hops, ip, cutoff):
        cards.update(_cards_for_user(hops, user_id, cutoff))
    return len(cards)


def _clustering_user(hops: list[SignalHop], user_id: str) -> dict[str, Any]:
    neigh: set[str] = set()
    for device_id in _devices_for_user(hops, user_id):
        neigh.update(_users_on_device(hops, device_id))
    neigh.discard(user_id)
    k = len(neigh)
    devices = _devices_for_user(hops, user_id)
    pick = devices[:CLUSTERING_MIN_DEVICES]
    n3 = 0
    if len(pick) >= CLUSTERING_MIN_DEVICES:
        for other in neigh:
            if all(other in _users_on_device(hops, d) for d in pick):
                n3 += 1
    coeff = 0.0
    if k >= 2:
        pairs = 0
        ordered = sorted(neigh)
        for i, a in enumerate(ordered):
            a_devs = set(_devices_for_user(hops, a))
            for b in ordered[i + 1 :]:
                if a_devs & set(_devices_for_user(hops, b)):
                    pairs += 1
        denom = k * (k - 1)
        if denom > 0:
            coeff = min(1.0, (2.0 * pairs) / float(denom))
    return {
        "coefficient": coeff,
        "accounts_sharing_three_devices": n3,
        "neighbor_user_count": k,
    }


def compute_graph_signals(
    anchor: Literal["user", "ip"],
    ref: str,
    hops: list[SignalHop],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Structural velocity + clustering. ``0`` counts are real; missing hops stay 0."""
    clock = now if now is not None else datetime.now(UTC)
    cutoff_ip = clock - GRAPH_SIGNALS_IP_VELOCITY_WINDOW
    cutoff_cards = clock - GRAPH_SIGNALS_TWO_HOP_CARD_WINDOW
    if anchor == "ip":
        by_lbl, total_deg = _degree(hops, LABEL_IP, ref)
        distinct_ip_users = len(_users_on_ip(hops, ref, cutoff_ip))
        two_hop_cards = _two_hop_cards_ip(hops, ref, cutoff_cards)
        cluster_block = {
            "coefficient": 0.0,
            "accounts_sharing_three_devices": 0,
            "neighbor_user_count": 0,
        }
        ip_vel = ip_velocity_block(distinct_users_last_2h=distinct_ip_users)
        entity_ref = f"ip:{ref}"
    else:
        by_lbl, total_deg = _degree(hops, LABEL_USER, ref)
        two_hop_cards = _two_hop_cards_user(hops, ref, cutoff_cards)
        cluster_block = _clustering_user(hops, ref)
        peak = 0
        for ip in _ips_for_user(hops, ref):
            peak = max(peak, len(_users_on_ip(hops, ip, cutoff_ip)))
        ip_vel = ip_velocity_block(distinct_users_last_2h=peak)
        entity_ref = ref
    return {
        "entity_ref": entity_ref,
        "anchor": anchor,
        "degree_centrality": {
            "total_distinct_neighbors": total_deg,
            "by_neighbor_label": by_lbl,
        },
        "two_hop_distinct_cards_last_2h": two_hop_cards,
        "clustering": cluster_block,
        "IP_VELOCITY": ip_vel,
        "backend": "janusgraph",
        "implemented": True,
        "status": "ok",
        "signals_usable": True,
        "signals_note": None,
    }
