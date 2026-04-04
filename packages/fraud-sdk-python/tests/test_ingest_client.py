"""Tests for EventIngestClient."""
from unittest.mock import MagicMock, patch

from fraud_stack_sdk.ingest_client import EventIngestClient


class TestEventIngestClient:
    def test_send_event(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "accepted": True,
            "stream_seq": 7,
            "ingest_id": "id-1",
        }
        ingest = EventIngestClient("http://ingest:8001", api_key="secret")
        with patch("httpx.Client") as MockClient:
            inst = MockClient.return_value.__enter__.return_value
            inst.post.return_value = mock_resp
            out = ingest.send_event(
                "t1", "login", "u1", payload={"x": 1}, idempotency_key="idem-xyz"
            )
            assert out["ingest_id"] == "id-1"
            assert out["stream_seq"] == 7
            inst.post.assert_called_once()
            args, kwargs = inst.post.call_args
            assert args[0] == "http://ingest:8001/v1/events"
            assert kwargs["json"]["tenant_id"] == "t1"
            assert kwargs["json"]["payload"] == {"x": 1}
            assert kwargs["headers"]["X-API-Key"] == "secret"
            assert kwargs["headers"]["Idempotency-Key"] == "idem-xyz"

    def test_send_batch(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "accepted": 2,
            "results": [
                {"ingest_id": "a", "seq": 1},
                {"ingest_id": "b", "seq": 2},
            ],
        }
        ingest = EventIngestClient("http://ingest:8001")
        events = [
            {"tenant_id": "t1", "event_type": "login", "entity_id": "u1", "payload": {}},
            {"tenant_id": "t1", "event_type": "payment", "entity_id": "u2", "payload": {}},
        ]
        with patch("httpx.Client") as MockClient:
            inst = MockClient.return_value.__enter__.return_value
            inst.post.return_value = mock_resp
            out = ingest.send_batch(events)
            assert out["accepted"] == 2
            assert len(out["results"]) == 2
            inst.post.assert_called_once()
            _, kwargs = inst.post.call_args
            assert kwargs["json"]["events"] == events
            assert "Idempotency-Key" not in kwargs["headers"]

    def test_send_batch_idempotency_header(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"accepted": 1, "results": [{"ingest_id": "x", "seq": 1}]}
        ingest = EventIngestClient("http://ingest:8001")
        events = [
            {"tenant_id": "t1", "event_type": "login", "entity_id": "u1", "payload": {}},
        ]
        with patch("httpx.Client") as MockClient:
            inst = MockClient.return_value.__enter__.return_value
            inst.post.return_value = mock_resp
            ingest.send_batch(events, idempotency_key="batch-xyz")
            _, kwargs = inst.post.call_args
            assert kwargs["headers"]["Idempotency-Key"] == "batch-xyz"
