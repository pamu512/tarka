"""Evaluate envelope: canonical JSON, signing, idempotency headers."""

import json

from fraud_stack_sdk.envelope import (
    build_evaluate_envelope,
    build_evaluate_request_headers,
    canonical_json_bytes,
)


def test_canonical_json_stable_key_order():
    a = canonical_json_bytes({"z": 1, "a": 2})
    b = canonical_json_bytes({"a": 2, "z": 1})
    assert a == b
    assert json.loads(a.decode()) == {"a": 2, "z": 1}


def test_build_evaluate_envelope_optional_fields():
    body = build_evaluate_envelope(
        tenant_id="t",
        event_type="login",
        entity_id="e",
        payload={"x": 1},
        session_id="s",
        metadata={"tls_pinning_verified": True},
        region="eu",
        challenge_policy_id="p1",
    )
    assert body["session_id"] == "s"
    assert body["metadata"]["tls_pinning_verified"] is True
    assert body["region"] == "eu"
    assert body["challenge_policy_id"] == "p1"


def test_request_headers_idempotency_and_signing():
    body = b'{"a":1}'
    h = build_evaluate_request_headers(
        api_key="k",
        body_bytes=body,
        request_secret="secret",
        signature_timestamp=1700000000,
        idempotency_key="idem-1",
        client_nonce="n1",
        client_timestamp=1700000001,
    )
    assert h["X-API-Key"] == "k"
    assert h["Idempotency-Key"] == "idem-1"
    assert h["X-Tarka-Client-Nonce"] == "n1"
    assert h["X-Tarka-Client-Timestamp"] == "1700000001"
    assert h["X-Tarka-Timestamp"] == "1700000000"
    assert "X-Tarka-Signature" in h
