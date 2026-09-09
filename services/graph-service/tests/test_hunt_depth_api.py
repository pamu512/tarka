"""D7.4 Path B: enforced Hunt depth-1. Walk cap stays 1."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from graph_service.hunt_depth import HUNT_DEPTH_MAX
from graph_service.main import app

SCHEMA_ID = "tarka.hunt_depth/v1"
HUNT_DEPTH_MAX = 1
DEPTH_CAPPED = "hunt:depth_capped"
_TENANT_A = "tenant_alpha"
_TENANT_B = "tenant_beta"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    with TestClient(app) as c:
        yield c


def _one_hop(seed: str = "user-a", neighbor: str = "dev-a") -> dict:
    return {
        "nodes": [
            {"id": seed, "labels": ["Person"], "properties": {"tenant_id": _TENANT_A}},
            {"id": neighbor, "labels": ["Device"], "properties": {"tenant_id": _TENANT_A}},
        ],
        "edges": [{"from_id": seed, "to_id": neighbor, "type": "USES_DEVICE", "properties": {}}],
    }


def _assert_honesty(body: dict, *, requested: int, applied: int, degrade: str | None) -> None:
    assert body["schema_id"] == SCHEMA_ID
    assert body["hunt_depth_max"] == HUNT_DEPTH_MAX
    assert body["depth_requested"] == requested
    assert body["depth_applied"] == applied
    assert body["degrade_reason"] == degrade


def test_path_b_hunt_depth_max_stays_one():
    from graph_service import age_client, hunt_depth

    assert hunt_depth.HUNT_DEPTH_MAX == 1
    assert hunt_depth.hunt_walk_depth(1) == 1
    assert hunt_depth.hunt_walk_depth(HUNT_DEPTH_MAX) == 1
    body = hunt_depth.attach_hunt_depth({"nodes": [], "edges": []}, 1, depth_applied=1)
    assert body["depth_applied"] == 1
    assert body["degrade_reason"] is None
    age_src = Path(age_client.__file__).read_text(encoding="utf-8")
    hunt_src = Path(hunt_depth.__file__).read_text(encoding="utf-8")
    assert "D7.4 to raise" not in age_src
    assert "Raise max only in D7.4+" not in hunt_src


def test_depth_one_reports_applied_one(client, monkeypatch):
    mock = AsyncMock(return_value=_one_hop())
    monkeypatch.setattr("graph_service.main.query_subgraph", mock)
    r = client.get(
        "/v1/subgraph",
        params={"tenant_id": _TENANT_A, "entity_id": "user-a", "depth": 1},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    _assert_honesty(body, requested=1, applied=1, degrade=None)
    assert body["nodes"]
    mock.assert_awaited_once()
    assert mock.await_args.args == (_TENANT_A, "user-a", 1)


def test_depth_equals_max_reports_applied_one_no_degrade(client, monkeypatch):
    mock = AsyncMock(return_value=_one_hop())
    monkeypatch.setattr("graph_service.main.query_subgraph", mock)
    r = client.get(
        "/v1/subgraph",
        params={"tenant_id": _TENANT_A, "entity_id": "user-a", "depth": HUNT_DEPTH_MAX},
    )
    assert r.status_code == 200, r.text
    _assert_honesty(r.json(), requested=HUNT_DEPTH_MAX, applied=1, degrade=None)
    assert mock.await_args.args == (_TENANT_A, "user-a", 1)


@pytest.mark.parametrize("requested", [2, 3, 5])
def test_depth_over_max_caps_walk_and_degrades(client, monkeypatch, requested):
    mock = AsyncMock(return_value=_one_hop())
    monkeypatch.setattr("graph_service.main.query_subgraph", mock)
    r = client.get(
        "/v1/subgraph",
        params={"tenant_id": _TENANT_A, "entity_id": "user-a", "depth": requested},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    _assert_honesty(body, requested=requested, applied=1, degrade=DEPTH_CAPPED)
    mock.assert_awaited_once()
    assert mock.await_args.args == (_TENANT_A, "user-a", 1)
    assert body.get("depth_applied") != requested
    assert "multi-hop success" not in json.dumps(body).lower()


def test_default_depth_two_is_capped_not_silent_success(client, monkeypatch):
    mock = AsyncMock(return_value=_one_hop())
    monkeypatch.setattr("graph_service.main.query_subgraph", mock)
    r = client.get("/v1/subgraph", params={"tenant_id": _TENANT_A, "entity_id": "user-a"})
    assert r.status_code == 200, r.text
    body = r.json()
    _assert_honesty(body, requested=2, applied=1, degrade=DEPTH_CAPPED)
    assert mock.await_args.args[2] == 1


def test_lookback_path_keeps_honesty_fields(client, monkeypatch):
    mock = AsyncMock(return_value=_one_hop())
    monkeypatch.setattr("graph_service.main.query_subgraph", mock)
    r = client.get(
        "/v1/subgraph",
        params={
            "tenant_id": _TENANT_A,
            "entity_id": "user-a",
            "depth": 5,
            "lookback_days": 90,
        },
    )
    assert r.status_code == 200, r.text
    _assert_honesty(r.json(), requested=5, applied=1, degrade=DEPTH_CAPPED)
    assert mock.await_args.args[2] == 1


def test_tenant_a_subgraph_does_not_leak_tenant_b(client, monkeypatch):
    async def _sub(tenant_id, entity_id, depth):
        assert depth == 1
        if tenant_id == _TENANT_A:
            return _one_hop(seed="shared-user", neighbor="dev-a")
        return {
            "nodes": [
                {
                    "id": "shared-user",
                    "labels": ["Person"],
                    "properties": {"tenant_id": _TENANT_B},
                },
                {
                    "id": "dev-b-secret",
                    "labels": ["Device"],
                    "properties": {"tenant_id": _TENANT_B},
                },
            ],
            "edges": [
                {
                    "from_id": "shared-user",
                    "to_id": "dev-b-secret",
                    "type": "USES_DEVICE",
                    "properties": {},
                }
            ],
        }

    monkeypatch.setattr("graph_service.main.query_subgraph", _sub)
    a = client.get(
        "/v1/subgraph",
        params={"tenant_id": _TENANT_A, "entity_id": "shared-user", "depth": 5},
    )
    b = client.get(
        "/v1/subgraph",
        params={"tenant_id": _TENANT_B, "entity_id": "shared-user", "depth": 1},
    )
    assert a.status_code == 200 and b.status_code == 200
    a_ids = {n["id"] for n in a.json()["nodes"]}
    b_ids = {n["id"] for n in b.json()["nodes"]}
    assert "dev-b-secret" not in a_ids
    assert "dev-a" in a_ids
    assert "dev-b-secret" in b_ids
    assert "dev-a" not in b_ids


@pytest.mark.asyncio
async def test_age_query_subgraph_cypher_is_tenant_scoped(monkeypatch):
    from graph_service import age_client

    stmts: list[str] = []

    class _Conn:
        async def fetch(self, stmt, *_a):
            stmts.append(stmt)
            return []

    class _Pool:
        def acquire(self):
            return self

        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, *_a):
            return False

    monkeypatch.setattr(age_client, "get_pool", AsyncMock(return_value=_Pool()))
    out = await age_client.query_subgraph(_TENANT_A, "shared-user", 5)
    assert out["nodes"] == []
    assert out["edges"] == []
    joined = "\n".join(stmts)
    assert _TENANT_A in joined
    assert _TENANT_B not in joined
    assert "nb.tenant_id" in joined


@pytest.mark.asyncio
async def test_age_query_subgraph_walk_is_one_hop_for_any_requested_depth(monkeypatch):
    from graph_service import age_client

    stmts: list[str] = []

    class _Conn:
        async def fetch(self, stmt, *_a):
            stmts.append(stmt)
            return []

    class _Pool:
        def acquire(self):
            return self

        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, *_a):
            return False

    monkeypatch.setattr(age_client, "get_pool", AsyncMock(return_value=_Pool()))
    await age_client.query_subgraph(_TENANT_A, "user-a", 1)
    hop_1 = [s for s in stmts if "RETURN e, nb" in s]
    stmts.clear()
    await age_client.query_subgraph(_TENANT_A, "user-a", 5)
    hop_5 = [s for s in stmts if "RETURN e, nb" in s]
    assert hop_1 and hop_5
    assert hop_1 == hop_5
    joined = hop_5[0]
    assert "MATCH (root)-[e]-(nb)" in joined
    assert "[*" not in joined
    assert "age_unnest" not in joined


@pytest.mark.asyncio
async def test_age_query_subgraph_drops_foreign_tenant_neighbor(monkeypatch):
    from graph_service import age_client

    root = {
        "id": "10",
        "label": "Person",
        "properties": {"external_id": "shared-user", "tenant_id": _TENANT_A},
    }
    leak = {
        "id": "99",
        "label": "Device",
        "properties": {"external_id": "dev-b-secret", "tenant_id": _TENANT_B},
    }
    edge = {
        "id": "e1",
        "label": "USES_DEVICE",
        "start_id": "10",
        "end_id": "99",
        "properties": {},
    }

    class _Conn:
        async def fetch(self, stmt, *_a):
            if "RETURN root" in stmt and "RETURN e, nb" not in stmt:
                return [{"root": json.dumps(root)}]
            return [{"e": json.dumps(edge), "nb": json.dumps(leak)}]

    class _Pool:
        def acquire(self):
            return self

        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, *_a):
            return False

    monkeypatch.setattr(age_client, "get_pool", AsyncMock(return_value=_Pool()))
    out = await age_client.query_subgraph(_TENANT_A, "shared-user", 5)
    ids = {n["id"] for n in out["nodes"]}
    assert "shared-user" in ids
    assert "dev-b-secret" not in ids
    assert out["edges"] == []
