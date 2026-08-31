from unittest.mock import AsyncMock

import pytest

from graph_service import age_client, janusgraph_gremlin, janusgraph_store, neo4j_client
from graph_service.entity_risk_score import SEARCH_PROP_KEYS, cypher_search_prop_predicate


class _RecordG:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def V(self, *_a):  # noqa: N802 — Gremlin traversal API
        self.calls.append(("V", _a))
        return self

    def has(self, *args):
        self.calls.append(("has", args))
        return self

    def limit(self, n):
        self.calls.append(("limit", n))
        return self

    def toList(self):  # noqa: N802 — Gremlin traversal API
        return []

    def both(self):
        return self


@pytest.mark.asyncio
async def test_janus_search_calls_prefix_has_with_tenant(monkeypatch):
    g = _RecordG()
    monkeypatch.setattr(janusgraph_store, "get_traversal_source", lambda: g)
    monkeypatch.setattr(janusgraph_store, "vertex_search_index_enabled", lambda: True)
    monkeypatch.setattr(janusgraph_store, "_batch_valuemap", lambda _g, verts: [])

    async def _immediate(fn):
        return fn()

    monkeypatch.setattr(janusgraph_store, "run_in_gremlin_thread", _immediate)
    rows, truncated = await janusgraph_store.search_entities("acme", "ali", limit=10)
    assert rows == []
    assert truncated is False
    has_args = [c[1] for c in g.calls if c[0] == "has"]
    assert any(args and args[0] == "tenant_id" and args[1] == "acme" for args in has_args)
    assert any(len(args) >= 2 and str(args[1]).find("textContainsPrefix") >= 0 for args in has_args)


def test_schema_ensure_groovy_emits_index_names():
    groovy = janusgraph_gremlin._schema_ensure_groovy()
    assert "vertexSearch" in groovy
    assert "byTenantExternal" in groovy
    for key in SEARCH_PROP_KEYS:
        assert key in groovy


@pytest.mark.asyncio
async def test_neo4j_search_sends_contains_and_tenant(monkeypatch):
    captured: dict[str, object] = {}

    class _Result:
        async def data(self):
            return []

    class _Session:
        async def run(self, cypher, **params):
            captured["cypher"] = cypher
            captured["params"] = params
            return _Result()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

    class _Driver:
        def session(self):
            return _Session()

    monkeypatch.setattr(neo4j_client, "get_driver", AsyncMock(return_value=_Driver()))
    rows, _trunc = await neo4j_client.search_entities("acme", "ali")
    assert rows == []
    cypher = str(captured["cypher"])
    assert "CONTAINS" in cypher or "contains" in cypher.lower()
    assert "$tenant_id" in cypher
    assert "$q" in cypher
    assert captured["params"]["tenant_id"] == "acme"
    assert captured["params"]["q"] == "ali"


@pytest.mark.asyncio
async def test_age_search_uses_tenant_literal_not_params(monkeypatch):
    captured: dict[str, object] = {}

    class _Conn:
        async def fetch(self, stmt, *args):
            captured.setdefault("stmts", []).append(stmt)
            captured.setdefault("args", []).append(args)
            return []

    class _Pool:
        def acquire(self):
            return self

        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, *_a):
            return False

    monkeypatch.setattr(age_client, "get_pool", AsyncMock(return_value=_Pool()))
    rows, _trunc = await age_client.search_entities("acme", "ali")
    assert rows == []
    stmt = " ".join(str(s) for s in captured.get("stmts") or [])
    assert '"acme"' in stmt
    assert "$tenant_id" not in stmt
    assert "$q" not in stmt
    assert "ali" not in stmt
    assert all(not args for args in captured.get("args") or [])
