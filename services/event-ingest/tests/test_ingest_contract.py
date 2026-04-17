"""Contract-first envelope and event_type validation (E1)."""

import json
import os
from unittest.mock import AsyncMock, patch

import pytest
from event_ingest.config import settings
from event_ingest.ingest_contract import IngestContractError, parse_ingest_event_body


os.environ.setdefault("NATS_URL", "nats://localhost:4222")


@pytest.fixture
def mock_js():
    js = AsyncMock()
    js.publish = AsyncMock(return_value=type("Ack", (), {"seq": 1})())
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


def test_parse_invalid_event_type():
    with pytest.raises(IngestContractError) as exc:
        parse_ingest_event_body(
            {"tenant_id": "t", "entity_id": "e", "event_type": "not_a_real_type", "payload": {}},
            envelope_mode="optional",
        )
    assert "ingest_event_type_invalid" in exc.value.reason_codes


def test_parse_v1_envelope(client, mock_js):
    r = client.post(
        "/v1/events",
        json={
            "schema_version": "1",
            "event": {
                "tenant_id": "t1",
                "event_type": "login",
                "entity_id": "u1",
                "payload": {"ip": "1.1.1.1"},
            },
        },
    )
    assert r.status_code == 200
    mock_js.publish.assert_called_once()


def test_required_envelope_rejects_flat(client, mock_js):
    prev = settings.ingest_envelope_mode
    settings.ingest_envelope_mode = "required"
    try:
        r = client.post(
            "/v1/events",
            json={"tenant_id": "t1", "event_type": "login", "entity_id": "u1", "payload": {}},
        )
        assert r.status_code == 422
        d = r.json()
        assert d["detail"]["error"] == "ingest_contract_violation"
        assert "ingest_envelope_required" in d["detail"]["reason_codes"]
        mock_js.publish.assert_not_called()
    finally:
        settings.ingest_envelope_mode = prev


def test_stats_after_reject(client, mock_js):
    r = client.post("/v1/events", json={"tenant_id": "t1", "event_type": "bad_type", "entity_id": "u1", "payload": {}})
    assert r.status_code == 422
    st = client.get("/v1/ingest/stats")
    assert st.status_code == 200
    data = st.json()
    assert data["total_contract_rejects"] >= 1
    assert data["contract_reject_by_reason"].get("ingest_event_type_invalid", 0) >= 1


def test_require_idempotency_key(client, mock_js):
    prev = settings.ingest_require_idempotency_key
    settings.ingest_require_idempotency_key = True
    try:
        r = client.post(
            "/v1/events",
            json={"tenant_id": "t1", "event_type": "login", "entity_id": "u1", "payload": {}},
        )
        assert r.status_code == 422
        assert "ingest_idempotency_key_required" in r.json()["detail"]["reason_codes"]
        mock_js.publish.assert_not_called()
    finally:
        settings.ingest_require_idempotency_key = prev
