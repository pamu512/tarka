"""Unit tests for the event-ingest service endpoints."""
import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import os
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


class TestHealthEndpoint:
    def test_health(self, client):
        r = client.get("/v1/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"


class TestIngestEvent:
    def test_single_event(self, client, mock_js):
        r = client.post("/v1/events", json={
            "tenant_id": "t1",
            "event_type": "login",
            "entity_id": "user-1",
            "payload": {"ip": "1.2.3.4"},
        })
        assert r.status_code == 200
        data = r.json()
        assert data["accepted"] is True
        assert "ingest_id" in data
        assert data["stream_seq"] == 42
        mock_js.publish.assert_called_once()

    def test_single_event_with_device_context(self, client, mock_js):
        r = client.post("/v1/events", json={
            "tenant_id": "t1",
            "event_type": "payment",
            "entity_id": "user-2",
            "payload": {"amount": 500},
            "device_context": {"device_id": "dev1", "platform": "ios"},
        })
        assert r.status_code == 200
        assert r.json()["accepted"] is True

    def test_single_event_validation_error(self, client):
        r = client.post("/v1/events", json={"tenant_id": "t1"})
        assert r.status_code == 422


class TestIngestBatch:
    def test_batch_events(self, client, mock_js):
        r = client.post("/v1/events/batch", json={
            "events": [
                {"tenant_id": "t1", "event_type": "login", "entity_id": "u1", "payload": {}},
                {"tenant_id": "t1", "event_type": "payment", "entity_id": "u2", "payload": {}},
                {"tenant_id": "t1", "event_type": "signup", "entity_id": "u3", "payload": {}},
            ]
        })
        assert r.status_code == 200
        data = r.json()
        assert data["accepted"] == 3
        assert len(data["results"]) == 3
        assert mock_js.publish.call_count == 3

    def test_batch_empty(self, client, mock_js):
        r = client.post("/v1/events/batch", json={"events": []})
        assert r.status_code == 200
        assert r.json()["accepted"] == 0


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
                            r = c.post("/v1/events", json={
                                "tenant_id": "t1",
                                "event_type": "login",
                                "entity_id": "u1",
                                "payload": {},
                            })
                            assert r.status_code == 503
