from __future__ import annotations

"""Resilient evaluate request envelope: canonical JSON, signing headers, idempotency hints."""


import json
import time
import uuid
from typing import Any

from fraud_stack_sdk.request_signing import build_signature_headers


def canonical_json_bytes(obj: dict[str, Any]) -> bytes:
    """Stable UTF-8 JSON for HMAC and retries (sorted keys, no extra whitespace)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def build_evaluate_envelope(
    *,
    tenant_id: str,
    event_type: str,
    entity_id: str,
    payload: dict[str, Any] | None = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    device_context: dict[str, Any] | None = None,
    region: str | None = None,
    challenge_policy_id: str | None = None,
) -> dict[str, Any]:
    """Assemble the Decision API evaluate JSON body (caller may add fields before canonicalization)."""
    body: dict[str, Any] = {
        "tenant_id": tenant_id,
        "event_type": event_type,
        "entity_id": entity_id,
        "payload": payload or {},
    }
    if session_id is not None:
        body["session_id"] = session_id
    if metadata is not None:
        body["metadata"] = metadata
    if device_context is not None:
        body["device_context"] = device_context
    if region is not None:
        body["region"] = region
    if challenge_policy_id is not None:
        body["challenge_policy_id"] = challenge_policy_id
    return body


def build_evaluate_request_headers(
    *,
    api_key: str = "",
    body_bytes: bytes,
    request_secret: str | None = None,
    signature_timestamp: int | None = None,
    idempotency_key: str | None = None,
    client_nonce: str | None = None,
    client_timestamp: int | None = None,
) -> dict[str, str]:
    """Headers for POST /v1/decisions/evaluate: API key, optional Idempotency-Key, replay hints, optional HMAC."""
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    if client_nonce:
        headers["X-Tarka-Client-Nonce"] = client_nonce
    if client_timestamp is not None:
        headers["X-Tarka-Client-Timestamp"] = str(int(client_timestamp))
    if request_secret:
        headers.update(
            build_signature_headers(body_bytes, secret=request_secret, timestamp=signature_timestamp),
        )
    return headers


def default_client_nonce() -> str:
    """Random UUID for X-Tarka-Client-Nonce (retry-safe when paired with Idempotency-Key)."""
    return str(uuid.uuid4())


def default_client_timestamp() -> int:
    """Unix seconds for X-Tarka-Client-Timestamp."""
    return int(time.time())
