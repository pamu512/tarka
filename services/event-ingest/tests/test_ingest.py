"""Unit tests for the event-ingest service endpoints."""

import json
import os
from unittest.mock import AsyncMock, patch

import pytest
from event_ingest.main import _payload_for_decision_api

os.environ.setdefault("NATS_URL", "nats://localhost:4222")


class _FakeAck:
    def __init__(self, seq: int = 1):
        self.seq = seq


@pytest.fixture
def mock_js():
    js = AsyncMock()
    js.publish = AsyncMock(return_value=_FakeAck(seq=42))
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


class TestIngestStats:
    def test_ingest_stats(self, client):
        r = client.get("/v1/ingest/stats")
        assert r.status_code == 200
        data = r.json()
        assert data["service"] == "event-ingest"
        assert data["total_contract_rejects"] == 0
        assert data["contract_reject_by_reason"] == {}
        assert data.get("envelope_mode") == "optional"
        assert data.get("require_idempotency_key") is False


class TestHealthEndpoint:
    def test_health(self, client):
        r = client.get("/v1/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "nats_connected" in data
        assert "redis_configured" in data
        if not data["redis_configured"]:
            assert data.get("redis_ok") is None
        else:
            assert data["redis_ok"] in (True, False)


class TestIdempotency:
    def test_same_key_second_call_duplicate(self, client, mock_js):
        import fakeredis.aioredis as fake_aioredis
        from event_ingest.main import app

        app.state.redis = fake_aioredis.FakeRedis(decode_responses=True)
        body = {"tenant_id": "t1", "event_type": "login", "entity_id": "u1", "payload": {}}
        r1 = client.post("/v1/events", json=body, headers={"Idempotency-Key": "pay-1"})
        assert r1.status_code == 200
        d1 = r1.json()
        assert d1.get("duplicate") is not True
        r2 = client.post("/v1/events", json=body, headers={"Idempotency-Key": "pay-1"})
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["duplicate"] is True
        assert d2["ingest_id"] == d1["ingest_id"]
        assert mock_js.publish.call_count == 1


class TestIngestEvent:
    def test_single_event(self, client, mock_js):
        r = client.post(
            "/v1/events",
            json={
                "tenant_id": "t1",
                "event_type": "login",
                "entity_id": "user-1",
                "payload": {"ip": "1.2.3.4"},
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["accepted"] is True
        assert "ingest_id" in data
        assert data["stream_seq"] == 42
        mock_js.publish.assert_called_once()

    def test_single_event_with_device_context(self, client, mock_js):
        r = client.post(
            "/v1/events",
            json={
                "tenant_id": "t1",
                "event_type": "payment",
                "entity_id": "user-2",
                "payload": {"amount": 500},
                "device_context": {"device_id": "dev1", "platform": "ios"},
            },
        )
        assert r.status_code == 200
        assert r.json()["accepted"] is True

    def test_single_event_validation_error(self, client):
        r = client.post("/v1/events", json={"tenant_id": "t1"})
        assert r.status_code == 422


class TestBatchIdempotency:
    def test_batch_duplicate_returns_cached(self, client, mock_js):
        import fakeredis.aioredis as fake_aioredis
        from event_ingest.main import app

        app.state.redis = fake_aioredis.FakeRedis(decode_responses=True)
        batch = {
            "events": [
                {"tenant_id": "t1", "event_type": "login", "entity_id": "u1", "payload": {}},
                {"tenant_id": "t1", "event_type": "payment", "entity_id": "u2", "payload": {}},
            ]
        }
        r1 = client.post("/v1/events/batch", json=batch, headers={"Idempotency-Key": "batch-1"})
        assert r1.status_code == 200
        d1 = r1.json()
        assert d1.get("duplicate") is not True
        assert d1["accepted"] == 2
        r2 = client.post("/v1/events/batch", json=batch, headers={"Idempotency-Key": "batch-1"})
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["duplicate"] is True
        assert d2["results"] == d1["results"]
        assert mock_js.publish.call_count == 2

    def test_batch_idempotency_key_in_json_body(self, client, mock_js):
        import fakeredis.aioredis as fake_aioredis
        from event_ingest.main import app

        app.state.redis = fake_aioredis.FakeRedis(decode_responses=True)
        batch = {
            "events": [{"tenant_id": "t1", "event_type": "login", "entity_id": "u1", "payload": {}}],
            "idempotency_key": "json-batch-key",
        }
        r1 = client.post("/v1/events/batch", json=batch)
        r2 = client.post("/v1/events/batch", json=batch)
        assert r1.json()["accepted"] == 1
        assert r2.json()["duplicate"] is True
        assert mock_js.publish.call_count == 1


class TestIngestBatch:
    def test_batch_events(self, client, mock_js):
        r = client.post(
            "/v1/events/batch",
            json={
                "events": [
                    {"tenant_id": "t1", "event_type": "login", "entity_id": "u1", "payload": {}},
                    {"tenant_id": "t1", "event_type": "payment", "entity_id": "u2", "payload": {}},
                    {"tenant_id": "t1", "event_type": "signup", "entity_id": "u3", "payload": {}},
                ]
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["accepted"] == 3
        assert len(data["results"]) == 3
        assert mock_js.publish.call_count == 3

    def test_batch_empty(self, client, mock_js):
        r = client.post("/v1/events/batch", json={"events": []})
        assert r.status_code == 200
        assert r.json()["accepted"] == 0


class TestPayloadForDecisionApi:
    def test_strips_ingest_id(self):
        raw = {
            "tenant_id": "t1",
            "event_type": "login",
            "entity_id": "u1",
            "payload": {},
            "_ingest_id": "abc123",
        }
        out = _payload_for_decision_api(raw)
        assert "_ingest_id" not in out
        assert out == {
            "tenant_id": "t1",
            "event_type": "login",
            "entity_id": "u1",
            "payload": {},
        }


class TestWebSocketIngest:
    def test_ws_valid_event(self, client, mock_js):
        with client.websocket_connect("/v1/events/ws") as ws:
            ws.send_text(
                json.dumps(
                    {
                        "tenant_id": "t1",
                        "event_type": "login",
                        "entity_id": "u1",
                        "payload": {},
                    }
                )
            )
            msg = ws.receive_json()
            assert msg["accepted"] is True
            assert "ingest_id" in msg
            assert msg["seq"] == 42
            mock_js.publish.assert_called()

    def test_ws_validation_error(self, client, mock_js):
        with client.websocket_connect("/v1/events/ws") as ws:
            ws.send_text(json.dumps({"tenant_id": "t1"}))
            msg = ws.receive_json()
            assert msg.get("error") in ("validation_error", "ingest_contract_violation")
            assert "detail" in msg or "reason_codes" in msg

    def test_ws_invalid_json(self, client, mock_js):
        with client.websocket_connect("/v1/events/ws") as ws:
            ws.send_text("not-json{")
            msg = ws.receive_json()
            assert msg.get("error") == "invalid JSON"


class TestNatsNotConnected:
    def test_event_fails_without_nats(self):
        with patch("event_ingest.main._js", None):
            with patch("event_ingest.main._connect_nats", new_callable=AsyncMock) as mock_connect:
                nc = AsyncMock()
                nc.is_connected = False
                nc.drain = AsyncMock()
                mock_connect.return_value = (nc, None)

                with patch("event_ingest.main.asyncio.create_task"):
                    from event_ingest.main import app
                    from fastapi.testclient import TestClient

                    with TestClient(app) as c:
                        with patch("event_ingest.main._js", None):
                            r = c.post(
                                "/v1/events",
                                json={
                                    "tenant_id": "t1",
                                    "event_type": "login",
                                    "entity_id": "u1",
                                    "payload": {},
                                },
                            )
                            assert r.status_code == 503
