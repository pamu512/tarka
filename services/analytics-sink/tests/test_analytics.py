"""Unit tests for the analytics-sink service — flush and query endpoints."""
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from analytics_sink.main import _flush_batch


# ---------- _flush_batch ----------


class TestFlushBatch:
    def test_flush_batch_inserts_rows(self):
        mock_client = MagicMock()
        with patch("analytics_sink.main._ch_client", mock_client):
            batch = [
                {
                    "trace_id": "tr1",
                    "tenant_id": "t1",
                    "entity_id": "e1",
                    "event_type": "login",
                    "decision": "allow",
                    "score": 15.0,
                    "tags": ["clean"],
                    "rule_hits": [],
                    "signal_tags": [],
                    "ml_score": 12.0,
                    "payload": {"ip": "1.2.3.4"},
                },
            ]
            _flush_batch("fraud", batch)

        mock_client.insert.assert_called_once()
        call_args = mock_client.insert.call_args
        assert call_args[0][0] == "fraud.decision_events"
        rows = call_args[0][1]
        assert len(rows) == 1
        assert rows[0][0] == "tr1"
        assert rows[0][4] == "allow"

    def test_flush_batch_handles_missing_fields(self):
        mock_client = MagicMock()
        with patch("analytics_sink.main._ch_client", mock_client):
            batch = [{"tenant_id": "t1"}]
            _flush_batch("fraud", batch)

        rows = mock_client.insert.call_args[0][1]
        assert rows[0][0] == ""
        assert rows[0][4] == "pending"

    def test_flush_batch_empty_list_is_noop(self):
        mock_client = MagicMock()
        with patch("analytics_sink.main._ch_client", mock_client):
            _flush_batch("fraud", [])
        mock_client.insert.assert_not_called()

    def test_flush_batch_no_client_is_noop(self):
        with patch("analytics_sink.main._ch_client", None):
            _flush_batch("fraud", [{"trace_id": "tr1"}])

    def test_flush_batch_insert_error_logged(self):
        mock_client = MagicMock()
        mock_client.insert.side_effect = Exception("connection refused")
        with patch("analytics_sink.main._ch_client", mock_client):
            _flush_batch("fraud", [{"trace_id": "tr1"}])

    def test_flush_batch_multiple_rows(self):
        mock_client = MagicMock()
        with patch("analytics_sink.main._ch_client", mock_client):
            batch = [
                {"trace_id": f"tr{i}", "tenant_id": "t1", "score": float(i * 10)}
                for i in range(5)
            ]
            _flush_batch("fraud", batch)

        rows = mock_client.insert.call_args[0][1]
        assert len(rows) == 5


# ---------- Query endpoints ----------


class _FakeQueryResult:
    def __init__(self, column_names, rows):
        self.column_names = column_names
        self.result_rows = rows


class TestQueryEndpoints:
    @pytest.fixture
    def client(self):
        mock_ch = MagicMock()
        mock_ch.query.return_value = _FakeQueryResult(
            column_names=["trace_id", "tenant_id", "entity_id", "decision", "score"],
            rows=[
                ("tr1", "t1", "e1", "deny", 85.0),
                ("tr2", "t1", "e2", "allow", 10.0),
            ],
        )
        with patch("analytics_sink.main._ch_client", mock_ch):
            with patch("analytics_sink.main._init_clickhouse"):
                with patch("analytics_sink.main.asyncio.create_task"):
                    from analytics_sink.main import app
                    from fastapi.testclient import TestClient
                    with TestClient(app) as c:
                        yield c

    def test_health(self, client):
        r = client.get("/v1/health")
        assert r.status_code == 200

    def test_query_decisions(self, client):
        r = client.get("/v1/analytics/decisions", params={"tenant_id": "t1"})
        assert r.status_code == 200
        data = r.json()
        assert "rows" in data
        assert len(data["rows"]) == 2
        assert data["rows"][0]["trace_id"] == "tr1"

    def test_query_decisions_with_filters(self, client):
        r = client.get("/v1/analytics/decisions", params={
            "tenant_id": "t1", "decision": "deny", "entity_id": "e1", "days": 30
        })
        assert r.status_code == 200

    def test_hourly_stats(self, client):
        r = client.get("/v1/analytics/hourly", params={"tenant_id": "t1"})
        assert r.status_code == 200

    def test_entity_history(self, client):
        r = client.get("/v1/analytics/entity/e1", params={"tenant_id": "t1"})
        assert r.status_code == 200

    def test_top_entities(self, client):
        r = client.get("/v1/analytics/top-entities", params={"tenant_id": "t1"})
        assert r.status_code == 200
