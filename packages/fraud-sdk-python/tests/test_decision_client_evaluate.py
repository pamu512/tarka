"""DecisionClient evaluate: canonical body, headers, optional strict parse."""

import json
from unittest.mock import MagicMock, patch

from fraud_stack_sdk.client import DecisionClient
from fraud_stack_sdk.evaluate_response import parse_evaluate_response


def _eval_response():
    return {
        "trace_id": "550e8400-e29b-41d4-a716-446655440000",
        "decision": "allow",
        "score": 10.0,
        "tags": [],
        "inference_context": {
            "schema_version": "3",
            "calibration_profile": "default",
            "expected_calibration_version": 1,
            "integrity_confidence": 0.5,
            "tamper_risk": 0.0,
            "network_trust": 0.8,
            "replay_risk": 0.0,
            "geo_consistency_risk": 0.0,
            "top_signals": [],
            "confidence_tier": "medium",
            "driver_reasons": [],
            "colocation_risk": 0.0,
            "copresence_risk": 0.0,
            "impossible_travel_risk": 0.0,
            "velocity_events_5m": 0,
            "velocity_events_1h": 0,
            "velocity_events_24h": 0,
        },
    }


def test_evaluate_sends_canonical_bytes_and_idempotency():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = _eval_response()
    client = DecisionClient("http://api:8000", api_key="k")
    with patch("httpx.Client") as MockClient:
        inst = MockClient.return_value.__enter__.return_value
        inst.post.return_value = mock_resp
        client.evaluate(
            "t1",
            "login",
            "e1",
            payload={"b": 2, "a": 1},
            idempotency_key="idem-x",
            replay_safe_headers=True,
            client_nonce="fixed-nonce",
            client_timestamp=1700000000,
        )
        inst.post.assert_called_once()
        _, kwargs = inst.post.call_args
        assert (
            kwargs["content"]
            == json.dumps(
                {
                    "entity_id": "e1",
                    "event_type": "login",
                    "payload": {"a": 1, "b": 2},
                    "tenant_id": "t1",
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        )
        hdrs = kwargs["headers"]
        assert hdrs["Idempotency-Key"] == "idem-x"
        assert hdrs["X-Tarka-Client-Nonce"] == "fixed-nonce"
        assert hdrs["X-Tarka-Client-Timestamp"] == "1700000000"


def test_evaluate_includes_role_in_canonical_body():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = _eval_response()
    client = DecisionClient("http://127.0.0.1:8000/decisions", api_key="k")
    with patch("httpx.Client") as MockClient:
        inst = MockClient.return_value.__enter__.return_value
        inst.post.return_value = mock_resp
        client.evaluate(
            "demo",
            "payment",
            "clone-demo-clean",
            payload={"amount": 25.0},
            role="member",
        )
        _, kwargs = inst.post.call_args
        assert inst.post.call_args.args[0] == (
            "http://127.0.0.1:8000/decisions/v1/decisions/evaluate"
        )
        body = json.loads(kwargs["content"].decode())
        assert body["role"] == "member"
        assert body["tenant_id"] == "demo"
        assert body["entity_id"] == "clone-demo-clean"


def test_evaluate_with_signing_secret_adds_hmac_headers():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = _eval_response()
    client = DecisionClient("http://api:8000", api_key="k", request_signing_secret="s3cr3t")
    with patch("httpx.Client") as MockClient:
        inst = MockClient.return_value.__enter__.return_value
        inst.post.return_value = mock_resp
        client.evaluate("t1", "login", "e1", payload={})
        _, kwargs = inst.post.call_args
        hdrs = kwargs["headers"]
        assert "X-Tarka-Timestamp" in hdrs
        assert "X-Tarka-Signature" in hdrs


def test_strict_client_validates_response():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = _eval_response()
    client = DecisionClient("http://api:8000", strict_evaluate_response=True)
    with patch("httpx.Client") as MockClient:
        inst = MockClient.return_value.__enter__.return_value
        inst.post.return_value = mock_resp
        out = client.evaluate("t1", "login", "e1")
    assert out == parse_evaluate_response(_eval_response())
