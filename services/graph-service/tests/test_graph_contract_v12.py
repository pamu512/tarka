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


def test_janus_upsert_identity_includes_vtype():
    """Lookup filter must include label so user:abc ≠ device:abc."""
    from graph_service import janusgraph_store as store

    assert store.vertex_lookup_uses_label() is True
    assert store.janus_graph_id_for("t", "user", "abc") == "jvg:t:user:abc"
    assert store.janus_graph_id_for("t", "device", "abc") == "jvg:t:device:abc"
    assert store.janus_graph_id_for("t", "user", "abc") != store.janus_graph_id_for(
        "t", "device", "abc"
    )


class _Rec:
    def __init__(self, data: dict | None) -> None:
        self._data = data

    def __getitem__(self, key):
        if self._data is None:
            raise KeyError(key)
        return self._data[key]

    def __bool__(self) -> bool:
        return self._data is not None


class _Result:
    def __init__(self, rec: dict | None) -> None:
        self._rec = _Rec(rec)

    async def single(self):
        return self._rec if self._rec else None


class _Session:
    def __init__(self, *, exist_roles: list[str] | None = None, gid: str = "gid-1") -> None:
        self.exist_roles = exist_roles
        self.gid = gid
        self.calls: list[tuple[str, dict]] = []

    async def run(self, cypher, **params):
        self.calls.append((cypher, params))
        if "RETURN n.roles" in cypher:
            if self.exist_roles is None:
                return _Result(None)
            return _Result({"roles": list(self.exist_roles)})
        if "RETURN elementId" in cypher or "RETURN node_list" in cypher:
            return _Result({"gid": self.gid, "node_list": [], "all_rels": []})
        return _Result(None)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False


class _Driver:
    def __init__(self, sessions: list[_Session]) -> None:
        self._sessions = list(sessions)

    def session(self):
        return self._sessions.pop(0)


@pytest.mark.asyncio
async def test_neo4j_upsert_user_and_device_same_id_are_distinct(monkeypatch):
    """Call the store: user:abc and device:abc MERGE as different labeled vertices."""
    from unittest.mock import AsyncMock

    from graph_service import neo4j_client

    s_user, s_dev = _Session(gid="u"), _Session(gid="d")
    monkeypatch.setattr(
        neo4j_client, "get_driver", AsyncMock(return_value=_Driver([s_user, s_dev]))
    )
    uid = await neo4j_client.upsert_entity("t1", "user", "abc", {"role": "member"})
    did = await neo4j_client.upsert_entity("t1", "device", "abc", {})
    assert uid != did
    user_merge = [q for q, _p in s_user.calls if "MERGE" in q]
    device_merge = [q for q, _p in s_dev.calls if "MERGE" in q]
    assert user_merge and "MERGE (n:user" in user_merge[0]
    assert device_merge and "MERGE (n:device" in device_merge[0]
    assert user_merge[0] != device_merge[0]


@pytest.mark.asyncio
async def test_neo4j_upsert_two_roles_one_vertex(monkeypatch):
    """Same user_id upserted twice keeps one vertex and merges roles[]."""
    from unittest.mock import AsyncMock

    from graph_service import neo4j_client

    first = _Session(exist_roles=None, gid="same")
    second = _Session(exist_roles=["cashier"], gid="same")
    monkeypatch.setattr(
        neo4j_client, "get_driver", AsyncMock(return_value=_Driver([first, second]))
    )
    a = await neo4j_client.upsert_entity("t1", "user", "u1", {"role": "cashier"})
    b = await neo4j_client.upsert_entity("t1", "user", "u1", {"role": "dispatcher"})
    assert a == b == "same"
    merge_params = [p for q, p in second.calls if "MERGE" in q]
    assert merge_params
    roles = merge_params[0]["properties"]["roles"]
    assert set(roles) == {"cashier", "dispatcher"}


@pytest.mark.asyncio
async def test_neo4j_store_refuses_unsigned_vtype_and_related(monkeypatch):
    from unittest.mock import AsyncMock

    from graph_service import neo4j_client

    monkeypatch.setattr(neo4j_client, "get_driver", AsyncMock(return_value=_Driver([_Session()])))
    with pytest.raises(gc.UnsignedGraphToken, match="vtype"):
        await neo4j_client.upsert_entity("t1", "spaceship", "x", {})
    monkeypatch.setattr(neo4j_client, "get_driver", AsyncMock(return_value=_Driver([_Session()])))
    with pytest.raises(gc.UnsignedGraphToken, match="etype"):
        await neo4j_client.create_link("t1", "a", "b", "RELATED", {})
    monkeypatch.setattr(neo4j_client, "get_driver", AsyncMock(return_value=_Driver([_Session()])))
    with pytest.raises(gc.UnsignedGraphToken, match="etype"):
        await neo4j_client.create_link("t1", "a", "b", "NOT_A_REAL_EDGE", {})


@pytest.mark.asyncio
async def test_neo4j_subgraph_and_risk_cypher_prefer_user_root(monkeypatch):
    """Evaluate hop roots on user when user:id and device:id both exist."""
    from unittest.mock import AsyncMock

    from graph_service import neo4j_client
    from graph_service.algorithms_neo4j import entity_risk_cypher

    sess = _Session()
    monkeypatch.setattr(neo4j_client, "get_driver", AsyncMock(return_value=_Driver([sess])))
    out = await neo4j_client.query_subgraph("t1", "abc", 2)
    assert out["nodes"] == []
    assert out["edges"] == []
    assert sess.calls, "query_subgraph must hit the store"
    q = sess.calls[0][0]
    # Runtime query (not source grep): bind user first; unique fallback only.
    assert ":user" in q
    assert "size(hits) = 1" in q
    risk_q = entity_risk_cypher(2)
    assert ":user" in risk_q
    assert "size(hits) = 1" in risk_q
