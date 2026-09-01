import pytest


@pytest.mark.asyncio
async def test_mirror_upserts_typed_objects_and_fills_resulted_in(monkeypatch):
    from graph_service import decision_graph_mirror as mirror
    from graph_service.janusgraph_store import ALLOWED_LABELS, ALLOWED_RELS

    assert {
        "Login",
        "Session",
        "Ip",
        "Document",
        "LicensePlate",
        "Decision",
        "Email",
        "Phone",
        "Place",
        "Address",
        "Card",
        "List",
    } <= ALLOWED_LABELS
    assert {
        "USED_DEVICE",
        "USED_SESSION",
        "USED_IP",
        "MADE_PAYMENT",
        "PERFORMED_LOGIN",
        "HAS_EMAIL",
        "HAS_PHONE",
        "HAS_CARD",
        "HAS_LIST",
        "RESULTED_IN",
        "BASED_ON",
        "SUPERSEDES",
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
            "external_id": "dec:tr-1",
            "kind": "evaluate",
            "outcome": "review",
            "trace_id": "tr-1",
            "objects": [
                {"external_id": "buyer-demo", "entity_type": "Person", "properties": {}},
                {"external_id": "login:tr-1", "entity_type": "Login", "properties": {}},
                {
                    "external_id": "dec:tr-1",
                    "entity_type": "Decision",
                    "properties": {"outcome": "review", "source": "evaluate"},
                },
            ],
            "object_links": [
                {
                    "from_external_id": "buyer-demo",
                    "to_external_id": "login:tr-1",
                    "relationship": "PERFORMED_LOGIN",
                },
                {
                    "from_external_id": "buyer-demo",
                    "to_external_id": "dec:tr-1",
                    "relationship": "RESULTED_IN",
                },
                {
                    "from_external_id": "dec:tr-1",
                    "to_external_id": "login:tr-1",
                    "relationship": "BASED_ON",
                },
            ],
        },
    )
    types = {row[1] for row in upserts}
    assert "Decision" in types
    assert {"Person", "Login", "Decision"} <= types
    assert any(
        rel == "RESULTED_IN" and src == "buyer-demo" and dst == "dec:tr-1"
        for _, src, dst, rel, _ in links
    )
    assert any(rel == "BASED_ON" and src == "dec:tr-1" for _, src, dst, rel, _ in links)
    assert any(rel == "PERFORMED_LOGIN" for _, _, _, rel, _ in links)


@pytest.mark.asyncio
async def test_mirror_synthesizes_decision_when_payload_omits_it(monkeypatch):
    from graph_service import decision_graph_mirror as mirror

    upserts: list[tuple] = []
    links: list[tuple] = []

    async def _upsert(tenant_id, entity_type, external_id, properties, tags=None):
        upserts.append((entity_type, external_id))
        return f"gid:{external_id}"

    async def _link(tenant_id, src, dst, rel, props=None):
        links.append((src, dst, rel))

    monkeypatch.setattr("graph_service.graph_runtime.upsert_entity", _upsert)
    monkeypatch.setattr("graph_service.graph_runtime.create_link", _link)

    await mirror._mirror_async(
        "demo",
        {
            "external_id": "dec_abc",
            "kind": "evaluate",
            "outcome": "deny",
            "trace_id": "tr-1",
            "entity_external_ids": ["buyer-demo"],
            "objects": [
                {"external_id": "buyer-demo", "entity_type": "Person", "properties": {}},
            ],
            "object_links": [],
        },
    )
    assert ("Decision", "dec_abc") in upserts
    assert ("buyer-demo", "dec_abc", "RESULTED_IN") in links


@pytest.mark.asyncio
async def test_schedule_mirror_awaits_on_loop(monkeypatch):
    from graph_service import decision_graph_mirror as mirror

    ran: list[str] = []

    async def _mirror(tenant_id, row):
        ran.append(tenant_id)

    monkeypatch.setenv("DECISION_GRAPH_JANUS_MIRROR", "1")
    monkeypatch.setattr(mirror, "_mirror_async", _mirror)
    await mirror.schedule_mirror("demo", {"external_id": "dec_1"})
    assert ran == ["demo"]


def test_mirror_defaults_on(monkeypatch):
    from graph_service import decision_graph_mirror as mirror

    monkeypatch.delenv("DECISION_GRAPH_JANUS_MIRROR", raising=False)
    assert mirror.mirror_enabled() is True
    monkeypatch.setenv("DECISION_GRAPH_JANUS_MIRROR", "0")
    assert mirror.mirror_enabled() is False


@pytest.mark.asyncio
async def test_trim_allow_window_deletes_oldest_allow(monkeypatch):
    from graph_service import graph_runtime as runtime

    deleted: list[str] = []

    async def _sub(tenant_id, entity_id, depth):
        assert tenant_id == "demo" and entity_id == "buyer"
        nodes = [
            {
                "id": f"dec:allow-{i}",
                "labels": ["Decision"],
                "properties": {
                    "source": "evaluate",
                    "outcome": "allow",
                    "kind": "evaluate",
                    "created_at": f"2026-08-31T00:{i:02d}:00Z",
                },
            }
            for i in range(21)
        ]
        nodes.append(
            {
                "id": "dec:deny-1",
                "labels": ["Decision"],
                "properties": {
                    "source": "evaluate",
                    "outcome": "deny",
                    "kind": "evaluate",
                    "created_at": "2026-08-01T00:00:00Z",
                },
            }
        )
        return {"nodes": nodes, "edges": []}

    async def _delete(tenant_id, external_id):
        deleted.append(external_id)

    monkeypatch.setattr(runtime, "query_subgraph", _sub)
    monkeypatch.setattr(runtime, "delete_entity", _delete)
    n = await runtime.trim_allow_decision_window("demo", "buyer")
    assert n == 1
    assert deleted == ["dec:allow-0"]


def test_merge_stored_trace_ids_keeps_history():
    from graph_service.graph_runtime import merge_stored_trace_ids

    assert merge_stored_trace_ids(["tr-1"], ["tr-2"]) == ["tr-1", "tr-2"]
    assert merge_stored_trace_ids('["tr-1"]', ["tr-2"]) == ["tr-1", "tr-2"]
    assert merge_stored_trace_ids(["tr-1", "tr-2"], ["tr-1"]) == ["tr-1", "tr-2"]
    assert len(merge_stored_trace_ids([f"tr-{i}" for i in range(40)], ["tr-new"])) == 32
    assert merge_stored_trace_ids([f"tr-{i}" for i in range(40)], ["tr-new"])[-1] == "tr-new"
