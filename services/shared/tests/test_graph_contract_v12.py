"""Graph contract v1.2 — identity, roles[], multi-id, refuse unsigned."""

from __future__ import annotations

import pytest

from graph_contract import (
    MemoryGraph,
    UnsignedGraphToken,
    consume_graph_answers,
    pack_why_from_graph_answers,
    register_roles,
    require_etype,
    require_role,
    require_vtype,
    reset_tenant_registry,
    vertex_key,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_tenant_registry()
    yield
    reset_tenant_registry()


def test_user_id_equal_device_id_does_not_merge():
    g = MemoryGraph("t1")
    g.upsert("user", "abc", properties={"role": "member"})
    g.upsert("device", "abc")
    assert g.get("user", "abc") is not None
    assert g.get("device", "abc") is not None
    assert g.get("user", "abc") is not g.get("device", "abc")
    assert len(g.vertices_for_id("abc")) == 2
    assert vertex_key("t1", "user", "abc") != vertex_key("t1", "device", "abc")


def test_same_user_two_roles_one_vertex():
    g = MemoryGraph("t1")
    g.upsert("user", "u1", properties={"role": "cashier"})
    g.upsert("user", "u1", properties={"role": "dispatcher"})
    node = g.get("user", "u1")
    assert node is not None
    assert set(node["properties"]["roles"]) == {"cashier", "dispatcher"}
    assert len(g.vertices_for_id("u1")) == 1


def test_shared_device_is_multi_id_not_written_share_edge():
    g = MemoryGraph("t1")
    g.upsert("user", "alice", properties={"role": "member"})
    g.upsert("user", "bob", properties={"role": "member"})
    g.upsert("device", "dev-1")
    g.create_link("alice", "dev-1", "USED", from_vtype="user", to_vtype="device")
    g.create_link("bob", "dev-1", "USED", from_vtype="user", to_vtype="device")
    answers = g.entity_risk_answers("alice")
    assert "bob" in answers["multi_id_user_ids"]
    types = {e["type"] for e in answers["named_edges"]}
    assert types == {"USED"}
    assert "SHARES_DEVICE" not in types
    assert "SAME_AS" not in types
    assert "RELATED" not in types


def test_unsigned_etype_refused_not_rewritten_to_related():
    g = MemoryGraph("t1")
    g.upsert("user", "a")
    g.upsert("user", "b")
    with pytest.raises(UnsignedGraphToken, match="etype"):
        g.create_link("a", "b", "NOT_A_REAL_EDGE", from_vtype="user", to_vtype="user")
    with pytest.raises(UnsignedGraphToken):
        require_etype("t1", "RELATED")  # RELATED is not a core write etype


def test_unsigned_vtype_refused():
    g = MemoryGraph("t1")
    with pytest.raises(UnsignedGraphToken, match="vtype"):
        g.upsert("spaceship", "x")
    with pytest.raises(UnsignedGraphToken):
        require_vtype("t1", "spaceship")


def test_unsigned_role_refused_when_registry_locked():
    register_roles("t1", ["member"])
    assert require_role("t1", "member") == "member"
    with pytest.raises(UnsignedGraphToken, match="role"):
        require_role("t1", "ghost")


def test_empty_role_registry_accepts_safe_role():
    # Tenant has not locked roles yet — any safe identifier is signed.
    assert require_role("open-tenant", "account_holder") == "account_holder"
    with pytest.raises(UnsignedGraphToken):
        require_role("open-tenant", "")


def test_consume_graph_answers_does_not_invent():
    empty = consume_graph_answers(None)
    assert empty["named_edges"] == []
    assert empty["multi_id_user_ids"] == []
    blob = {
        "risk_score": 12,
        "named_edges": [{"from_id": "u1", "to_id": "d1", "type": "USED"}],
        "multi_id_user_ids": ["u2"],
        "roles": ["member"],
    }
    got = consume_graph_answers(blob)
    assert got["named_edges"][0]["type"] == "USED"
    assert got["multi_id_user_ids"] == ["u2"]
    why = pack_why_from_graph_answers(got)
    assert why["invented_edges"] is False
    assert why["named_edges"][0]["type"] == "USED"
