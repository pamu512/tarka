"""Subgraph walk plans: undirected OR-join forbidden at scale.

Contract: AGE-backed neighbor walks (`list_one_hop_ids`, `query_subgraph`)
must resolve the anchor vertex's graphid first and then run DIRECTED edge
lookups anchored on `id(<const>)` — never a single undirected `(e.start=x AND
e.end=y) OR (e.end=x AND e.start=y)` join. The OR shape forces Postgres into
a nested-loop cross product over the edge space (cost ~8.9e8 at 100k
entities, >16 min); the directed anchored shape uses ix_<label>_start/_end
btree indexes deterministically at any scale.

These are behavioral contracts on the SQL text age_client emits — the same
discipline as test_link_ddl_race: no string-gate on docs, gates on the SQL
that actually runs.
"""

from __future__ import annotations

import re

from graph_service import age_client


def _sql_of(fn, *args, **kwargs):
    """Capture the SQL strings a store function would execute."""
    queries: list[str] = []

    class FakeConn:
        async def fetch(self, q, *a):
            queries.append(q)
            return []

        async def fetchrow(self, q, *a):
            queries.append(q)
            return None

    class FakeCtx:
        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, *exc):
            return False

    import pytest

    return queries, pytest.MonkeyPatch()


def test_list_one_hop_ids_uses_two_phase_directed_plan(monkeypatch):
    import asyncio

    queries: list[str] = []

    class FakeConn:
        async def fetch(self, q, *a):
            queries.append(q)
            return []

        async def fetchrow(self, q, *a):
            queries.append(q)
            if "RETURN id" in q or "id(n)" in q:
                return {"gid": "1234567890123456789"}
            return None

    class FakeCtx:
        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(age_client, "_acquire", lambda: FakeCtx())
    out = asyncio.run(age_client.list_one_hop_ids("t0", "e0"))

    sql = "\n".join(queries)
    # Phase 1 must resolve the anchor graphid via a labeled/indexed lookup.
    assert "id(n)" in sql or "RETURN id" in sql, "no anchor-resolution query emitted"
    # Phase 2 edge queries must be directed (either direction), never an
    # undirected OR-join.
    edge_queries = [q for q in queries if "MATCH" in q and ("-[r]-" in q or "-[e]-" in q)]
    assert edge_queries, "no edge walk queries emitted"
    for q in edge_queries:
        assert " OR " not in q.upper(), f"undirected OR-join still present: {q[:120]}"
        # anchored on a resolved id, not property-filtered on both endpoints
        assert "id(n) = " in q or "id(root) = " in q, f"edge walk not id-anchored: {q[:120]}"


def test_query_subgraph_uses_directed_edge_walk(monkeypatch):
    import asyncio

    queries: list[str] = []

    class FakeConn:
        async def fetch(self, q, *a):
            queries.append(q)
            if "RETURN root, id(root)" in q:
                return [{"root": "{}", "gid": "123"}]
            return []

        async def fetchrow(self, q, *a):
            queries.append(q)
            return {"gid": "1234567890123456789"}

    class FakeCtx:
        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(age_client, "_acquire", FakeCtx)
    asyncio.run(age_client.query_subgraph("t0", "e0", 1))

    sql = "\n".join(queries)
    edge_queries = [q for q in queries if "MATCH" in q and "-[" in q]
    assert edge_queries, "no edge walk emitted"
    for q in edge_queries:
        assert " OR " not in q.upper(), f"undirected OR-join in subgraph walk: {q[:120]}"
        assert "id(root) = " in q or "id(n) = " in q, f"not id-anchored: {q[:120]}"
