import pytest


@pytest.mark.asyncio
async def test_mirror_upserts_typed_objects_and_fills_resulted_in(monkeypatch):
    from graph_service import decision_graph_mirror as mirror
    from graph_service.janusgraph_store import ALLOWED_LABELS, ALLOWED_RELS

    assert {"Login", "Session", "Ip", "Document", "LicensePlate"} <= ALLOWED_LABELS
    assert {
        "USED_DEVICE",
        "USED_SESSION",
        "USED_IP",
        "MADE_PAYMENT",
        "PERFORMED_LOGIN",
        "RESULTED_IN",
        "BASED_ON",
    } <= ALLOWED_RELS

    upserts: list[tuple] = []
    links: list[tuple] = []

    async def _upsert(tenant_id, entity_type, external_id, properties, tags=None):
        upserts.append((tenant_id, entity_type, external_id, properties, tags))
        return f"gid:{external_id}"

    async def _link(tenant_id, src, dst, rel, props=None):
        links.append((tenant_id, src, dst, rel, props))

    monkeypatch.setattr("graph_service.graph_runtime.upsert_entity", _upsert)
    monkeypatch.setattr("graph_service.graph_runtime.create_link", _link)

    await mirror._mirror_async(
        "demo",
        {
            "external_id": "dec_abc",
            "kind": "evaluate",
            "outcome": "review",
            "trace_id": "tr-1",
            "objects": [
                {"external_id": "buyer-demo", "entity_type": "Person", "properties": {}},
                {"external_id": "login:tr-1", "entity_type": "Login", "properties": {}},
            ],
            "object_links": [
                {
                    "from_external_id": "buyer-demo",
                    "to_external_id": "login:tr-1",
                    "relationship": "PERFORMED_LOGIN",
                },
                {
                    "from_external_id": "login:tr-1",
                    "to_external_id": "",
                    "relationship": "RESULTED_IN",
                },
            ],
        },
    )
    types = {row[1] for row in upserts}
    assert "Decision" not in types
    assert {"Person", "Login"} <= types
    assert not any(rel == "RESULTED_IN" for _, _, _, rel, _ in links)
    assert not any(src == "dec_abc" or dst == "dec_abc" for _, src, dst, _, _ in links)
    assert any(rel == "PERFORMED_LOGIN" for _, _, _, rel, _ in links)


@pytest.mark.asyncio
async def test_schedule_mirror_runs_on_caller_loop(monkeypatch):
    import asyncio

    from graph_service import decision_graph_mirror as mirror

    monkeypatch.setenv("DECISION_GRAPH_JANUS_MIRROR", "1")
    loops: list[asyncio.AbstractEventLoop] = []

    async def _cap(tid, row):
        loops.append(asyncio.get_running_loop())

    monkeypatch.setattr(mirror, "_mirror_async", _cap)
    here = asyncio.get_running_loop()
    await mirror.schedule_mirror("demo", {"external_id": "x"})
    assert loops == [here]


@pytest.mark.asyncio
async def test_age_upsert_merges_trace_ids(monkeypatch):
    from graph_service import age_client
    from graph_service.graph_runtime import merge_stored_trace_ids

    stmts: list[str] = []

    class _Conn:
        async def fetchrow(self, q, *a):
            stmts.append(q)
            if "n.trace_ids" in q and "SET" not in q:
                return {"tids": '["tr-1"]'}
            return {"gid": "1"}

    class _CM:
        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, *a):
            return False

    async def _pool():
        return object()

    monkeypatch.setattr(age_client, "get_pool", _pool)
    monkeypatch.setattr(age_client, "get_allowed_labels", lambda tid: None)
    monkeypatch.setattr(age_client, "require_vtype", lambda tid, t: t)
    monkeypatch.setattr(age_client, "_acquire", lambda: _CM())
    gid = await age_client.upsert_entity(
        "acme", "Person", "u1", {"trace_ids": ["tr-2"]}
    )
    assert gid == "1"
    blob = "\n".join(stmts)
    merged = merge_stored_trace_ids(["tr-1"], ["tr-2"])
    assert "tr-1" in blob and "tr-2" in blob
    assert merged == ["tr-1", "tr-2"]
    assert "$$, %s)" not in blob
    assert "cypher('tarka'" in blob


@pytest.mark.asyncio
async def test_init_pool_reloads_age_on_checkout_reset(monkeypatch):
    from graph_service import age_client

    captured: dict = {}

    async def _fake_pool(*a, **k):
        captured.update(k)
        return object()

    monkeypatch.setattr(age_client, "_pool", None)
    monkeypatch.setattr(age_client.asyncpg, "create_pool", _fake_pool)
    await age_client.init_pool()
    assert captured.get("reset") is age_client._reset_age_connection
    age_client._pool = None


def test_merge_stored_trace_ids_keeps_history():
    from graph_service.graph_runtime import merge_stored_trace_ids

    assert merge_stored_trace_ids(["tr-1"], ["tr-2"]) == ["tr-1", "tr-2"]
    assert merge_stored_trace_ids('["tr-1"]', ["tr-2"]) == ["tr-1", "tr-2"]
    assert merge_stored_trace_ids(["tr-1", "tr-2"], ["tr-1"]) == ["tr-1", "tr-2"]
    assert len(merge_stored_trace_ids([f"tr-{i}" for i in range(40)], ["tr-new"])) == 32
    assert merge_stored_trace_ids([f"tr-{i}" for i in range(40)], ["tr-new"])[-1] == "tr-new"
