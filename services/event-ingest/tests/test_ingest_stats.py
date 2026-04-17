"""GET /v1/ingest/stats contract reject counters."""

import json
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def mock_js():
    js = AsyncMock()
    js.publish = AsyncMock()
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


def test_ingest_stats_after_contract_reject(client, mock_js):
    r = client.post("/v1/events", json={"tenant_id": "t", "event_type": "bad_type", "entity_id": "e", "payload": {}})
    assert r.status_code == 422
    s = client.get("/v1/ingest/stats")
    assert s.status_code == 200
    data = s.json()
    assert data["contract_rejects_total"] >= 1
    assert "ingest_event_type_invalid" in data["contract_rejects_by_reason"]
