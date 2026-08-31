"""Mapped ingest is a second AGE writer. Wrong join key is a different Person."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from graph_service.mapped_ingest import ObjectMapping, plan_mapped_object
from graph_service.main import app


def test_plan_join_key_is_the_person_id_not_a_merge():
    mapping = ObjectMapping(
        join_field="user_id",
        object_field="device_id",
        object_type="Device",
        relationship="USED_DEVICE",
    )
    on_p = plan_mapped_object(
        source="file",
        mapping=mapping,
        record={"user_id": "p1", "device_id": "dev-9", "os": "ios"},
    )
    assert on_p["person_id"] == "p1"
    assert on_p["object_id"] == "dev-9"
    assert on_p["object_props"]["source"] == "file"
    assert on_p["object_props"]["os"] == "ios"
    other = plan_mapped_object(
        source="file",
        mapping=mapping,
        record={"user_id": "p2", "device_id": "dev-9"},
    )
    assert other["person_id"] == "p2"
    assert other["person_id"] != on_p["person_id"]


def test_plan_rejects_empty_source_or_join():
    mapping = ObjectMapping(
        join_field="user_id",
        object_field="device_id",
        object_type="Device",
        relationship="USED_DEVICE",
    )
    with pytest.raises(ValueError, match="source"):
        plan_mapped_object(source="  ", mapping=mapping, record={"user_id": "p", "device_id": "d"})
    with pytest.raises(ValueError, match="join key"):
        plan_mapped_object(
            source="file", mapping=mapping, record={"user_id": "  ", "device_id": "d"}
        )


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    with TestClient(app) as c:
        yield c


def test_ingest_joins_same_person_evaluate_would_write(client, monkeypatch):
    upserts: list[tuple[str, str, str | None]] = []
    links: list[tuple[str, str, str, str | None]] = []

    async def _upsert(tenant_id, entity_type, external_id, properties, tags=None):
        upserts.append((entity_type, external_id, (properties or {}).get("source")))
        return "gid"

    async def _link(tenant_id, src, dst, rel, properties):
        links.append((src, dst, rel, (properties or {}).get("source")))

    monkeypatch.setattr("graph_service.main.upsert_entity", _upsert)
    monkeypatch.setattr("graph_service.graph_runtime.upsert_entity", _upsert)
    monkeypatch.setattr("graph_service.graph_runtime.create_link", _link)
    monkeypatch.setattr("graph_service.main.refresh_touched_and_neighbors", AsyncMock())

    ev = client.post(
        "/v1/entities",
        json={
            "tenant_id": "acme",
            "entity_type": "Person",
            "external_id": "p1",
            "properties": {"source": "evaluate"},
        },
    )
    assert ev.status_code == 200, ev.text

    r = client.post(
        "/v1/ingest/objects",
        json={
            "tenant_id": "acme",
            "source": "file",
            "mapping": {
                "join_field": "user_id",
                "object_field": "device_id",
                "object_type": "Device",
                "relationship": "USED_DEVICE",
            },
            "record": {"user_id": "p1", "device_id": "dev-9"},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["person_id"] == "p1"
    assert body["object_id"] == "dev-9"
    assert body["source"] == "file"
    assert ("Person", "p1", "evaluate") in upserts
    assert ("Person", "p1", "file") in upserts
    assert ("Device", "dev-9", "file") in upserts
    assert ("p1", "dev-9", "USED_DEVICE", "file") in links
