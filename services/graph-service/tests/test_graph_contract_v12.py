"""Graph-service contract v1.2 — refuse unsigned, identity, entity-risk answers."""

from __future__ import annotations

import pytest
from graph_service.schemas import EntityRiskResponse
from graph_service.entity_risk_score import score_entity_risk

import graph_contract as gc


@pytest.fixture(autouse=True)
def _clean_registry():
    gc.reset_tenant_registry()
    yield
    gc.reset_tenant_registry()


def test_entity_risk_response_includes_named_edges_and_multi_id():
    model = EntityRiskResponse.model_validate(
        {
            "entity_id": "u1",
            "risk_score": 10.0,
            "named_edges": [{"from_id": "u1", "to_id": "d1", "type": "USED"}],
            "multi_id_user_ids": ["u2"],
            "roles": ["member"],
        }
    )
    dumped = model.model_dump()
    assert dumped["named_edges"][0]["type"] == "USED"
    assert dumped["multi_id_user_ids"] == ["u2"]
    assert dumped["roles"] == ["member"]


def test_score_entity_risk_carries_graph_answers():
    base = score_entity_risk(
        entity_id="u1",
        tags=[],
        conn_count=1,
        flagged=0,
        community_size=2,
        shared_devices=1,
        neighbor_device_count=1,
        relation_growth_1h=0,
        relation_growth_24h=0,
        peer_p90=None,
        checkpoint=None,
        profile="standard",
        hop_depth=2,
        freshness=None,
    )
    answers = gc.graph_answers_from_neighborhood(
        "u1",
        [
            {
                "id": "u1",
                "labels": ["user"],
                "properties": {"roles": ["member"]},
            },
            {"id": "u2", "labels": ["user"], "properties": {}},
            {"id": "d1", "labels": ["device"], "properties": {}},
        ],
        [
            {"from_id": "u1", "to_id": "d1", "type": "USED"},
            {"from_id": "u2", "to_id": "d1", "type": "USED"},
        ],
    )
    base.update(answers)
    model = EntityRiskResponse.model_validate(base)
    assert "u2" in model.multi_id_user_ids
    assert model.named_edges[0]["type"] == "USED"
    assert model.roles == ["member"]


def test_sanitize_rel_refuses_unknown_does_not_rewrite_related():
    from graph_service.janusgraph_store import refuse_rel

    with pytest.raises(gc.UnsignedGraphToken):
        refuse_rel("t1", "NOT_A_REAL_EDGE")
    with pytest.raises(gc.UnsignedGraphToken):
        refuse_rel("t1", "RELATED")
    assert refuse_rel("t1", "USED") == "USED"


def test_sanitize_label_refuses_unknown():
    from graph_service.janusgraph_store import refuse_label

    with pytest.raises(gc.UnsignedGraphToken):
        refuse_label("t1", "spaceship")
    assert refuse_label("t1", "user") == "user"


def test_janus_upsert_identity_includes_vtype(monkeypatch):
    """Lookup filter must include label so user:abc ≠ device:abc."""
    from graph_service import janusgraph_store as store

    assert store.vertex_lookup_uses_label() is True
    assert store.janus_graph_id_for("t", "user", "abc") == "jvg:t:user:abc"
    assert store.janus_graph_id_for("t", "device", "abc") == "jvg:t:device:abc"


def test_entity_risk_cypher_prefers_user_label():
    from graph_service.algorithms_neo4j import entity_risk_cypher

    src = entity_risk_cypher(2)
    assert "OPTIONAL MATCH (u:user" in src
    assert "size(hits) = 1" in src


def test_neo4j_upsert_merge_is_label_scoped():
    import inspect

    from graph_service import neo4j_client

    src = inspect.getsource(neo4j_client.upsert_entity)
    assert "MERGE (n:{label}" in src
    assert "tenant_id: $tenant_id, external_id: $external_id" in src


def test_neo4j_subgraph_prefers_user():
    import inspect

    from graph_service import neo4j_client

    src = inspect.getsource(neo4j_client.query_subgraph)
    assert "OPTIONAL MATCH (u:user" in src
    assert "size(hits) = 1" in src
