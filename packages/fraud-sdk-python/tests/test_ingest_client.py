"""Tests for EventIngestClient."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from fraud_stack_sdk.ingest_client import (
    EventIngestClient,
    apply_agent_mandate,
    compose_ingest_event,
    mandate_expired,
)


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

    def test_absent_actor_stays_missing(self):
        body = compose_ingest_event("t1", "login", "u1", payload={"x": 1})
        assert "actor_kind" not in body
        assert "score" not in body
        assert "decision" not in body
        assert body["payload"] == {"x": 1}

    def test_agent_out_of_mandate_sets_expired_and_omits_empty_caps(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        body = compose_ingest_event(
            "t1",
            "login",
            "u1",
            actor_kind="agent",
            mandate_caps={},
            mandate_expires_at="2020-01-01T00:00:00Z",
            now=now,
        )
        assert body["actor_kind"] == "agent"
        assert "mandate_caps" not in body
        assert body["mandate_expired"] is True
        assert "score" not in body
        assert "decision" not in body

    def test_in_mandate_keeps_caps_without_expired_flag(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        body = compose_ingest_event(
            "t1",
            "login",
            "u1",
            actor_kind="agent",
            mandate_caps={"spend_limit": 10},
            mandate_expires_at="2099-01-01T00:00:00Z",
            now=now,
        )
        assert body["mandate_caps"] == {"spend_limit": 10}
        assert "mandate_expired" not in body

    def test_unparseable_expiry_is_out_of_mandate(self):
        body = apply_agent_mandate(
            {
                "actor_kind": "agent",
                "mandate_caps": {"spend_limit": 1},
                "mandate_expires_at": "not-a-date",
            }
        )
        assert body["mandate_expired"] is True

    def test_epoch_millis_and_agent_case_stay_out_of_mandate(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        past_ms = datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000
        future_ms = datetime(2099, 1, 1, tzinfo=timezone.utc).timestamp() * 1000
        past = apply_agent_mandate(
            {
                "actor_kind": "AGENT",
                "mandate_caps": {"spend_limit": 1},
                "mandate_expires_at": past_ms,
            },
            now=now,
        )
        assert past["actor_kind"] == "agent"
        assert past["mandate_expired"] is True
        assert "score" not in past
        future = apply_agent_mandate(
            {
                "actor_kind": "Agent",
                "mandate_caps": {"spend_limit": 1},
                "mandate_expires_at": future_ms,
            },
            now=now,
        )
        assert future["actor_kind"] == "agent"
        assert "mandate_expired" not in future
        assert mandate_expired(past_ms, now) is True
        assert mandate_expired(future_ms, now) is False
        assert mandate_expired(
            datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp(), now
        ) is True

    def test_send_event_posts_agent_mandate_receipt(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"accepted": True, "stream_seq": 1, "ingest_id": "rec-1"}
        ingest = EventIngestClient("http://ingest:8001")
        with patch("httpx.Client") as MockClient:
            inst = MockClient.return_value.__enter__.return_value
            inst.post.return_value = mock_resp
            out = ingest.send_event(
                "t1",
                "login",
                "u1",
                actor_kind="agent",
                mandate_caps={"spend_limit": 5},
                mandate_expires_at="2020-01-01T00:00:00Z",
            )
        assert out["ingest_id"] == "rec-1"
        _args, kwargs = inst.post.call_args
        posted = kwargs["json"]
        assert posted["actor_kind"] == "agent"
        assert posted["mandate_expired"] is True
        assert "score" not in posted
        assert "decision" not in posted
