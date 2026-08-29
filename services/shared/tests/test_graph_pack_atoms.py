"""graph_v1 pack atoms — hop predicates, not a score blob."""

from __future__ import annotations

import pytest

from graph_contract import (
    UnsignedGraphToken,
    register_etypes,
    reset_tenant_registry,
)
from graph_pack_atoms import (
    HOP_FEATURE_KEY,
    SCHEMA_ID,
    attach_hop_to_features,
    eval_graph_v1,
    hop_view_from_graph_meta,
    hop_view_from_snapshot,
    pack_why_from_hop,
    require_pack_etype,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_tenant_registry()
    yield
    reset_tenant_registry()


def _shared_device_hop(*, flagged: bool = True) -> dict:
    return {
        "named_edges": [
            {"from_id": "alice", "to_id": "dev-1", "type": "USES_DEVICE"},
            {"from_id": "bob", "to_id": "dev-1", "type": "USES_DEVICE"},
        ],
        "multi_id_user_ids": ["bob"],
        "roles": ["member"],
        "sibling_y_labels": {"bob": "1"} if flagged else {},
        "flagged_user_ids": ["bob"] if flagged else [],
        "vertices": [
            {
                "id": "alice",
                "vtype": "user",
                "kind": "user",
                "roles": ["member"],
            },
            {
                "id": "bob",
                "vtype": "user",
                "kind": "user",
                "roles": ["member"],
                "y_label": "1" if flagged else "0",
                "properties": {"y_label": "1" if flagged else "0"},
            },
            {"id": "dev-1", "vtype": "device", "kind": "bridge"},
        ],
        "edges": [
            {"from_id": "alice", "to_id": "dev-1", "type": "USES_DEVICE"},
            {"from_id": "bob", "to_id": "dev-1", "type": "USES_DEVICE"},
        ],
    }


def test_shared_device_and_flagged_sibling_fires():
    hop = hop_view_from_graph_meta(
        _shared_device_hop(),
        graph_url="http://graph.test",
        tenant_id="t1",
        subject_id="alice",
    )
    assert hop["status"] == "graph:ok"
    assert eval_graph_v1("has_etype", hop, etype="USES_DEVICE", tenant_id="t1") is True
    assert eval_graph_v1("has_multi_id", hop, tenant_id="t1") is True
    assert eval_graph_v1("sibling_prior_flag", hop, tenant_id="t1") is True


def test_empty_url_does_not_fire_and_says_graph_missing():
    hop = hop_view_from_graph_meta(
        _shared_device_hop(),
        graph_url="",
        tenant_id="t1",
        subject_id="alice",
    )
    assert hop["status"] == "graph:missing"
    assert hop["named_edges"] == []
    assert hop["multi_id_user_ids"] == []
    assert eval_graph_v1("has_etype", hop, etype="USES_DEVICE", tenant_id="t1") is False
    assert eval_graph_v1("has_multi_id", hop, tenant_id="t1") is False
    assert eval_graph_v1("sibling_prior_flag", hop, tenant_id="t1") is False


def test_graph_missing_tag_does_not_invent_neighbors():
    hop = hop_view_from_graph_meta(
        _shared_device_hop(),
        graph_url="http://graph.test",
        degrade_tags=["graph:missing"],
        tenant_id="t1",
        subject_id="alice",
    )
    assert hop["status"] == "graph:missing"
    assert hop["named_edges"] == []
    assert eval_graph_v1("has_etype", hop, etype="USES_DEVICE", tenant_id="t1") is False


def test_unsigned_etype_refused_not_related():
    with pytest.raises(UnsignedGraphToken, match="etype"):
        require_pack_etype("t1", "RELATED")
    with pytest.raises(UnsignedGraphToken, match="etype"):
        require_pack_etype("t1", "NOT_A_REAL_EDGE")
    hop = hop_view_from_graph_meta(
        {
            "named_edges": [
                {"from_id": "a", "to_id": "b", "type": "RELATED"},
            ]
        },
        graph_url="http://graph.test",
        tenant_id="t1",
    )
    assert eval_graph_v1("has_etype", hop, etype="RELATED", tenant_id="t1") is False
    assert eval_graph_v1("has_etype", hop, etype="GHOST", tenant_id="t1") is False


def test_tenant_registered_etype_can_fire():
    register_etypes("t1", ["LOYALTY_TIE"])
    hop = hop_view_from_graph_meta(
        {
            "named_edges": [
                {"from_id": "alice", "to_id": "card-1", "type": "LOYALTY_TIE"},
            ]
        },
        graph_url="http://graph.test",
        tenant_id="t1",
    )
    assert eval_graph_v1("has_etype", hop, etype="LOYALTY_TIE", tenant_id="t1") is True
    assert eval_graph_v1("has_etype", hop, etype="LOYALTY_TIE", tenant_id="other") is False


def test_replay_from_snapshot_matches_live_hop():
    live_blob = _shared_device_hop()
    live = hop_view_from_graph_meta(
        live_blob,
        graph_url="http://graph.test",
        tenant_id="t1",
        subject_id="alice",
    )
    snapshot = {
        "graph_hop_v1": live,
        "pack_why": {"graph": pack_why_from_hop(live)},
        "subgraph_snapshot": {
            "status": "graph:ok",
            "tenant_id": "t1",
            "entity_id": "alice",
            "vertices": live_blob["vertices"],
            "edges": live_blob["edges"],
        },
    }
    replayed = hop_view_from_snapshot(snapshot, tenant_id="t1", subject_id="alice")
    assert replayed["status"] == live["status"]
    for atom, etype in (
        ("has_etype", "USES_DEVICE"),
        ("has_multi_id", None),
        ("sibling_prior_flag", None),
    ):
        assert eval_graph_v1(atom, live, etype=etype, tenant_id="t1") == eval_graph_v1(
            atom, replayed, etype=etype, tenant_id="t1"
        )
        assert eval_graph_v1(atom, live, etype=etype, tenant_id="t1") is True


def test_replay_does_not_derive_named_edges_from_gnn_edges():
    snap = hop_view_from_snapshot(
        {
            "subgraph_snapshot": {
                "status": "graph:ok",
                "vertices": [{"id": "alice", "vtype": "user"}],
                "edges": [
                    {"from_id": "alice", "to_id": "dev-1", "type": "USES_DEVICE"},
                ],
            }
        },
        tenant_id="t1",
        subject_id="alice",
    )
    assert snap["named_edges"] == []
    assert eval_graph_v1("has_etype", snap, etype="USES_DEVICE", tenant_id="t1") is False


def test_replay_does_not_invent_when_snapshot_is_graph_missing():
    snap = hop_view_from_snapshot(
        {
            "subgraph_snapshot": {
                "status": "graph:missing",
                "vertices": [],
                "edges": [],
            }
        },
        tenant_id="t1",
        subject_id="alice",
    )
    assert snap["status"] == "graph:missing"
    assert snap["named_edges"] == []
    assert eval_graph_v1("has_etype", snap, etype="USES_DEVICE", tenant_id="t1") is False


def test_attach_hop_uses_versioned_feature_key():
    hop = hop_view_from_graph_meta(
        _shared_device_hop(),
        graph_url="http://graph.test",
        tenant_id="t1",
    )
    feats: dict = {"amount": 10}
    attach_hop_to_features(feats, hop)
    assert feats[HOP_FEATURE_KEY]["schema_id"] == SCHEMA_ID
    assert feats[HOP_FEATURE_KEY]["named_edges"][0]["type"] == "USES_DEVICE"


def test_core_used_etype_is_signed():
    hop = hop_view_from_graph_meta(
        {"named_edges": [{"from_id": "u1", "to_id": "d1", "type": "USED"}]},
        graph_url="http://graph.test",
        tenant_id="t1",
    )
    assert eval_graph_v1("has_etype", hop, etype="USED", tenant_id="t1") is True


def test_sibling_prior_flag_lifts_without_multi_id():
    hop = hop_view_from_graph_meta(
        {
            "named_edges": [{"from_id": "alice", "to_id": "dev-1", "type": "USES_DEVICE"}],
            "multi_id_user_ids": [],
            "sibling_y_labels": {"bob": "FLAG"},
            "vertices": [
                {"id": "alice", "vtype": "user"},
                {"id": "bob", "vtype": "user", "properties": {"y_label": "1"}},
            ],
        },
        graph_url="http://graph.test",
        tenant_id="t1",
        subject_id="alice",
    )
    assert hop["multi_id_user_ids"] == []
    assert hop["sibling_flags"]
    assert eval_graph_v1("has_multi_id", hop, tenant_id="t1") is False
    assert eval_graph_v1("sibling_prior_flag", hop, tenant_id="t1") is True
    assert eval_graph_v1("has_etype", hop, etype="USES_DEVICE", tenant_id="t1") is True


def test_pack_why_names_atom_etype_or_graph_missing():
    missing = hop_view_from_graph_meta(
        _shared_device_hop(),
        graph_url="",
        tenant_id="t1",
        subject_id="alice",
    )
    why_missing = pack_why_from_hop(missing)
    assert why_missing["status"] == "graph:missing"
    assert why_missing["named"] == "graph:missing"
    assert why_missing["fired"] == []

    live = hop_view_from_graph_meta(
        _shared_device_hop(),
        graph_url="http://graph.test",
        tenant_id="t1",
        subject_id="alice",
    )
    why = pack_why_from_hop(live)
    assert why["named"] == "has_etype:USES_DEVICE+has_multi_id+sibling_prior_flag"
    assert any(
        x.get("atom") == "has_etype" and x.get("etype") == "USES_DEVICE" for x in why["fired"]
    )
