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
    import inspect

    sched = inspect.getsource(mirror.schedule_mirror)
    assert "asyncio.run" not in sched
    assert "threading" not in sched


def test_age_upsert_merges_trace_ids():
    import inspect

    from graph_service import age_client

    src = inspect.getsource(age_client.upsert_entity)
    assert "merge_stored_trace_ids" in src
    assert "_cypher_sql" in src
    assert "_set_literals" in src
    assert "$$, %s)" not in inspect.getsource(age_client)
    pool_src = inspect.getsource(age_client.init_pool)
    assert "reset=_reset_age_connection" in pool_src


def test_merge_stored_trace_ids_keeps_history():
    from graph_service.graph_runtime import merge_stored_trace_ids

    assert merge_stored_trace_ids(["tr-1"], ["tr-2"]) == ["tr-1", "tr-2"]
    assert merge_stored_trace_ids('["tr-1"]', ["tr-2"]) == ["tr-1", "tr-2"]
    assert merge_stored_trace_ids(["tr-1", "tr-2"], ["tr-1"]) == ["tr-1", "tr-2"]
    assert len(merge_stored_trace_ids([f"tr-{i}" for i in range(40)], ["tr-new"])) == 32
    assert merge_stored_trace_ids([f"tr-{i}" for i in range(40)], ["tr-new"])[-1] == "tr-new"
