"""Janus/Gremlin structural signals — pure hops, no Neo4j / tarka wheel."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

_SRC_ORCH = Path(__file__).resolve().parents[1]
if str(_SRC_ORCH) not in sys.path:
    sys.path.insert(0, str(_SRC_ORCH))

from graph_signals import (  # noqa: E402
    LABEL_CARD,
    LABEL_DEVICE,
    LABEL_IP,
    LABEL_USER,
    REL_ORDERED_FROM_IP,
    REL_PAID_WITH_CARD,
    REL_USED_DEVICE,
    SignalHop,
    compute_graph_signals,
)


def _hop(
    src_label: str,
    src_id: str,
    rel: str,
    dst_label: str,
    dst_id: str,
    *,
    observed_at: datetime | None = None,
) -> SignalHop:
    return SignalHop(
        src_label=src_label,
        src_id=src_id,
        rel=rel,
        dst_label=dst_label,
        dst_id=dst_id,
        observed_at=observed_at,
    )


def test_janus_signals_ip_velocity_spike_from_hops() -> None:
    now = datetime.now(UTC)
    hops = [
        _hop(LABEL_USER, f"u{i}", REL_ORDERED_FROM_IP, LABEL_IP, "10.0.0.9", observed_at=now)
        for i in range(10)
    ]
    signals = compute_graph_signals("ip", "10.0.0.9", hops, now=now)
    assert signals["implemented"] is True
    assert signals["signals_usable"] is True
    assert signals["backend"] == "janusgraph"
    assert signals["IP_VELOCITY"]["distinct_users_last_2h"] == 10
    assert signals["IP_VELOCITY"]["spike"] is True
    assert signals["degree_centrality"]["total_distinct_neighbors"] == 10


def test_janus_signals_two_hop_cards_and_clustering() -> None:
    now = datetime.now(UTC)
    hops = [
        _hop(LABEL_USER, "anchor", REL_ORDERED_FROM_IP, LABEL_IP, "1.1.1.1", observed_at=now),
        _hop(LABEL_USER, "other", REL_ORDERED_FROM_IP, LABEL_IP, "1.1.1.1", observed_at=now),
        _hop(LABEL_USER, "other", REL_PAID_WITH_CARD, LABEL_CARD, "card-9", observed_at=now),
        _hop(LABEL_USER, "anchor", REL_USED_DEVICE, LABEL_DEVICE, "d1", observed_at=now),
        _hop(LABEL_USER, "other", REL_USED_DEVICE, LABEL_DEVICE, "d1", observed_at=now),
        _hop(LABEL_USER, "anchor", REL_USED_DEVICE, LABEL_DEVICE, "d2", observed_at=now),
        _hop(LABEL_USER, "peer", REL_USED_DEVICE, LABEL_DEVICE, "d2", observed_at=now),
        _hop(LABEL_USER, "other", REL_USED_DEVICE, LABEL_DEVICE, "d2", observed_at=now),
    ]
    signals = compute_graph_signals("user", "anchor", hops, now=now)
    assert signals["two_hop_distinct_cards_last_2h"] == 1
    assert signals["clustering"]["neighbor_user_count"] == 2
    assert signals["clustering"]["coefficient"] > 0.0


def test_zero_hops_is_scored_zero_not_missing() -> None:
    signals = compute_graph_signals("user", "nobody", [], now=datetime.now(UTC))
    assert signals["degree_centrality"]["total_distinct_neighbors"] == 0
    assert signals["two_hop_distinct_cards_last_2h"] == 0
    assert signals["IP_VELOCITY"]["distinct_users_last_2h"] == 0
    assert signals["implemented"] is True


def test_gremlin_scalar_unwraps_tinkerpop_lists() -> None:
    from graph_signals import gremlin_scalar

    assert gremlin_scalar(["u1"]) == "u1"
    assert gremlin_scalar("u1") == "u1"
    assert gremlin_scalar([]) == ""
    assert gremlin_scalar(None) == ""


def test_collect_hops_reaches_other_users_cards() -> None:
    from graph_signals import LABEL_CARD, LABEL_IP, LABEL_USER, collect_signal_hops

    now = datetime.now(UTC)
    graph = {
        (LABEL_USER, "anchor"): [
            _hop(LABEL_USER, "anchor", REL_ORDERED_FROM_IP, LABEL_IP, "1.1.1.1", observed_at=now),
        ],
        (LABEL_IP, "1.1.1.1"): [
            _hop(LABEL_USER, "anchor", REL_ORDERED_FROM_IP, LABEL_IP, "1.1.1.1", observed_at=now),
            _hop(LABEL_USER, "other", REL_ORDERED_FROM_IP, LABEL_IP, "1.1.1.1", observed_at=now),
        ],
        (LABEL_USER, "other"): [
            _hop(LABEL_USER, "other", REL_ORDERED_FROM_IP, LABEL_IP, "1.1.1.1", observed_at=now),
            _hop(LABEL_USER, "other", REL_PAID_WITH_CARD, LABEL_CARD, "card-9", observed_at=now),
        ],
    }

    def fetch(label: str, _key: str, node_id: str):
        return list(graph.get((label, node_id), []))

    hops = collect_signal_hops(fetch, LABEL_USER, "anchor")
    signals = compute_graph_signals("user", "anchor", hops, now=now)
    assert signals["two_hop_distinct_cards_last_2h"] == 1


def test_device_hardware_risk_from_device_hops_is_not_implemented() -> None:
    from graph_signals import device_hardware_risk_from_hops

    now = datetime.now(UTC)
    hops = [
        _hop(LABEL_USER, "u1", REL_USED_DEVICE, LABEL_DEVICE, "dev-1", observed_at=now),
        _hop(LABEL_USER, "u2", REL_USED_DEVICE, LABEL_DEVICE, "dev-1", observed_at=now),
    ]
    risk = device_hardware_risk_from_hops("dev-1", hops, current_user_id="u1")
    assert risk["users_on_device"] == 1
    assert risk["blocked_user_count_on_device"] == 0
    assert risk["linked_to_blocked_node"] is False
    assert risk["implemented"] is False
    assert risk["signals_usable"] is False
