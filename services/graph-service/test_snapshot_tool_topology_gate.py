"""Gate (Prompt 110): neighborhood snapshot JSON reflects anchor → 1-hop → 2-hop topology."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import snapshot_tool  # noqa: E402


def test_topology_linear_chain_anchor_device_user() -> None:
    """Anchor User → Device (1-hop) → User (2-hop); JSON encodes depths and edge labels."""
    pytest.importorskip("gremlin_python")
    from gremlin_python.process.traversal import T

    anchor = {
        T.id: 100,
        T.label: snapshot_tool.LABEL_USER,
        "user_id": "u0",
        "tenant_id": "t1",
    }
    e_anchor_device = {T.id: 501, T.label: "USED_DEVICE", "transaction_id": "tx-1"}
    device = {
        T.id: 200,
        T.label: snapshot_tool.LABEL_DEVICE,
        "device_id": "dev-1",
        "tenant_id": "t1",
    }
    e_device_user = {T.id: 502, T.label: "RELATED", "role": "shared"}
    user2 = {T.id: 300, T.label: snapshot_tool.LABEL_USER, "user_id": "u2", "tenant_id": "t1"}

    one_hop = [{"edge": e_anchor_device, "neighbor": device}]

    def two_hop(nid: object, anchor_tid: object) -> list[dict]:
        assert anchor_tid == 100
        if nid == 200:
            return [{"edge": e_device_user, "vertex": user2}]
        return []

    tree = snapshot_tool.build_neighborhood_tree_from_gremlin_maps(
        user_id="u0",
        anchor_em=anchor,
        one_hop_edge_vertex_rows=one_hop,
        two_hop_fetcher=two_hop,
    )

    assert tree["schema"] == "janusgraph.neighborhood_snapshot.v1"
    assert tree["found"] is True
    assert tree["anchor"]["properties"]["user_id"] == "u0"
    assert tree["anchor"]["label"] == snapshot_tool.LABEL_USER

    assert len(tree["one_hop"]) == 1
    b1 = tree["one_hop"][0]
    assert b1["depth"] == 1
    assert b1["vertex"]["label"] == snapshot_tool.LABEL_DEVICE
    assert b1["vertex"]["properties"]["device_id"] == "dev-1"
    assert b1["edge_from_anchor"]["label"] == "USED_DEVICE"
    assert b1["edge_from_anchor"]["properties"]["transaction_id"] == "tx-1"

    assert len(b1["two_hop"]) == 1
    b2 = b1["two_hop"][0]
    assert b2["depth"] == 2
    assert b2["vertex"]["properties"]["user_id"] == "u2"
    assert b2["edge_from_one_hop"]["label"] == "RELATED"


def test_topology_star_two_devices_share_anchor() -> None:
    """Two 1-hop branches from the same anchor; 2-hop lists are independent per branch."""
    pytest.importorskip("gremlin_python")
    from gremlin_python.process.traversal import T

    anchor = {T.id: 1, T.label: snapshot_tool.LABEL_USER, "user_id": "anchor"}
    d1 = {T.id: 11, T.label: snapshot_tool.LABEL_DEVICE, "device_id": "d-a"}
    d2 = {T.id: 12, T.label: snapshot_tool.LABEL_DEVICE, "device_id": "d-b"}
    rows = [
        {"edge": {T.id: 101, T.label: "USED_DEVICE"}, "neighbor": d1},
        {"edge": {T.id: 102, T.label: "USED_DEVICE"}, "neighbor": d2},
    ]

    def two_hop(nid: object, _anchor: object) -> list[dict]:
        if nid == 11:
            return [
                {
                    "edge": {T.id: 201, T.label: "SEEN_ON"},
                    "vertex": {T.id: 99, T.label: snapshot_tool.LABEL_IP, "address": "203.0.113.9"},
                }
            ]
        if nid == 12:
            return []
        return []

    tree = snapshot_tool.build_neighborhood_tree_from_gremlin_maps(
        user_id="anchor",
        anchor_em=anchor,
        one_hop_edge_vertex_rows=rows,
        two_hop_fetcher=two_hop,
    )
    assert len(tree["one_hop"]) == 2
    by_dev = {b["vertex"]["properties"]["device_id"]: b for b in tree["one_hop"]}
    assert set(by_dev) == {"d-a", "d-b"}
    assert len(by_dev["d-a"]["two_hop"]) == 1
    assert by_dev["d-a"]["two_hop"][0]["vertex"]["label"] == snapshot_tool.LABEL_IP
    assert len(by_dev["d-b"]["two_hop"]) == 0
