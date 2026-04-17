"""Contract-first ingest envelope (E1)."""

import json
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def mock_js():
    js = AsyncMock()

    class _Ack:
        seq = 99

    js.publish = AsyncMock(return_value=_Ack())
    return js


@pytest.fixture
def client(mock_js):
    with patch("event_ingest.main._connect_nats", new_callable=AsyncMock) as mock_connect:
        nc = AsyncMock()
        nc.is_connected = True
        nc.drain = AsyncMock()
        mock_connect.return_value = (nc, mock_js)
        with patch("event_ingest.main.asyncio.create_task"):
            from event_ingest.main import app
            from fastapi.testclient import TestClient

            with TestClient(app) as c:
                yield c


def test_envelope_v1_accepted(client, mock_js):
    body = {
        "schema_version": "1",
        "event": {
            "tenant_id": "t1",
            "event_type": "login",
            "entity_id": "u1",
            "payload": {"x": 1},
        },
    }
    r = client.post("/v1/events", json=body)
    assert r.status_code == 200
    assert r.json()["accepted"] is True
    call = mock_js.publish.call_args
    payload_bytes = call[0][1]
    published = json.loads(payload_bytes.decode())
    assert published["tenant_id"] == "t1"
    assert published["event_type"] == "login"
    assert "_ingest_id" in published


def test_invalid_event_type_422(client, mock_js):
    r = client.post(
        "/v1/events",
        json={"tenant_id": "t1", "event_type": "unknown_kind", "entity_id": "u1", "payload": {}},
    )
    assert r.status_code == 422
    d = r.json()
    assert d["detail"]["reason_codes"] == ["ingest_event_type_invalid"]


def test_envelope_mode_required_rejects_flat(client, mock_js):
    with patch("event_ingest.main.settings") as s:
        s.ingest_envelope_mode = "required"
        s.ingest_require_idempotency_key = False
        s.subject_prefix = "fraud.events"
        s.idempotency_key_prefix = "ingest:idemp"
        s.idempotency_ttl_seconds = 86400
        s.nats_url = "nats://localhost:4222"
        s.decision_api_url = "http://localhost:8000"
        s.stream_name = "FRAUD_EVENTS"
        s.max_batch_size = 256
        s.api_keys = ""
        s.redis_url = ""
        r = client.post(
            "/v1/events",
            json={"tenant_id": "t1", "event_type": "login", "entity_id": "u1", "payload": {}},
        )
    assert r.status_code == 422
    assert "ingest_schema_required" in r.json()["detail"]["reason_codes"]


def test_require_idempotency_key_422(client, mock_js):
    with patch("event_ingest.main.settings") as s:
        s.ingest_require_idempotency_key = True
        s.ingest_envelope_mode = "optional"
        s.subject_prefix = "fraud.events"
        s.idempotency_key_prefix = "ingest:idemp"
        s.idempotency_ttl_seconds = 86400
        s.nats_url = "nats://localhost:4222"
        s.decision_api_url = "http://localhost:8000"
        s.stream_name = "FRAUD_EVENTS"
        s.max_batch_size = 256
        s.api_keys = ""
        s.redis_url = ""
        r = client.post(
            "/v1/events",
            json={"tenant_id": "t1", "event_type": "login", "entity_id": "u1", "payload": {}},
        )
    assert r.status_code == 422
    assert r.json()["detail"]["reason_codes"] == ["ingest_idempotency_key_required"]


def test_batch_envelope_item(client, mock_js):
    r = client.post(
        "/v1/events/batch",
        json={
            "events": [
                {"schema_version": "1", "event": {"tenant_id": "t1", "event_type": "payment", "entity_id": "u2", "payload": {}}},
            ]
        },
    )
    assert r.status_code == 200
    assert r.json()["accepted"] == 1
