from __future__ import annotations

from typing import Any, NotRequired, TypedDict
from uuid import UUID

import httpx

from fraud_stack_sdk.envelope import (
    build_evaluate_envelope,
    build_evaluate_request_headers,
    canonical_json_bytes,
    default_client_nonce,
    default_client_timestamp,
)
from fraud_stack_sdk.signals import ServerSignalCollector


class InferenceContext(TypedDict):
    schema_version: str
    calibration_profile: str
    expected_calibration_version: int
    integrity_confidence: float
    tamper_risk: float
    network_trust: float
    replay_risk: float
    geo_consistency_risk: float
    top_signals: list[str]
    confidence_tier: str
    driver_reasons: list[str]
    colocation_risk: float
    copresence_risk: float
    impossible_travel_risk: float
    velocity_events_5m: int
    velocity_events_1h: int
    velocity_events_24h: int
    confidence_tier_label: NotRequired[str]
    driver_explain: NotRequired[list[dict[str, Any]]]
    ml_top_factors: NotRequired[list[dict[str, Any]]]
    ml_summary: NotRequired[str | None]
    ml_model: NotRequired[str | None]


class EvaluateResponse(TypedDict, total=False):
    trace_id: str
    decision: str
    score: float
    tags: list[str]
    rule_hits: list[str]
    reasons: list[str]
    ml_score: float | None
    inference_context: InferenceContext
    recommended_action: str | None
    challenge_policy_id: NotRequired[str | None]
    challenge_metadata: NotRequired[dict[str, Any] | None]
    graph_decision_explanation: NotRequired[dict[str, Any] | None]


class DecisionClient:
    """Thin client for Decision API with optional server-side signal collection."""

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        timeout: float = 10.0,
        server_signals: bool = False,
        *,
        request_signing_secret: str | None = None,
        strict_evaluate_response: bool = False,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._collector = ServerSignalCollector() if server_signals else None
        self._request_signing_secret = request_signing_secret
        self._strict_evaluate_response = strict_evaluate_response

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            h["X-API-Key"] = self._api_key
        return h

    def evaluate(
        self,
        tenant_id: str,
        event_type: str,
        entity_id: str,
        payload: dict[str, Any] | None = None,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        device_context: dict[str, Any] | None = None,
        client_ip: str | None = None,
        request_headers: dict[str, str] | None = None,
        *,
        region: str | None = None,
        challenge_policy_id: str | None = None,
        idempotency_key: str | None = None,
        replay_safe_headers: bool = False,
        client_nonce: str | None = None,
        client_timestamp: int | None = None,
    ) -> EvaluateResponse:
        if self._collector and client_ip:
            device_context = self._collector.build_device_context(
                ip=client_ip,
                headers=request_headers,
                client_device_context=device_context,
            )

        body = build_evaluate_envelope(
            tenant_id=tenant_id,
            event_type=event_type,
            entity_id=entity_id,
            payload=payload,
            session_id=session_id,
            metadata=metadata,
            device_context=device_context,
            region=region,
            challenge_policy_id=challenge_policy_id,
        )
        body_bytes = canonical_json_bytes(body)
        nonce = client_nonce
        ts = client_timestamp
        if replay_safe_headers:
            if nonce is None:
                nonce = default_client_nonce()
            if ts is None:
                ts = default_client_timestamp()
        headers = build_evaluate_request_headers(
            api_key=self._api_key,
            body_bytes=body_bytes,
            request_secret=self._request_signing_secret,
            idempotency_key=idempotency_key,
            client_nonce=nonce,
            client_timestamp=ts,
        )

        with httpx.Client(timeout=self._timeout) as client:
            r = client.post(
                f"{self._base}/v1/decisions/evaluate",
                content=body_bytes,
                headers=headers,
            )
            r.raise_for_status()
            data = r.json()
            if self._strict_evaluate_response:
                from fraud_stack_sdk.evaluate_response import parse_evaluate_response

                return parse_evaluate_response(data)
            return data

    async def evaluate_async(
        self,
        tenant_id: str,
        event_type: str,
        entity_id: str,
        payload: dict[str, Any] | None = None,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        device_context: dict[str, Any] | None = None,
        client_ip: str | None = None,
        request_headers: dict[str, str] | None = None,
        *,
        region: str | None = None,
        challenge_policy_id: str | None = None,
        idempotency_key: str | None = None,
        replay_safe_headers: bool = False,
        client_nonce: str | None = None,
        client_timestamp: int | None = None,
    ) -> EvaluateResponse:
        if self._collector and client_ip:
            device_context = self._collector.build_device_context(
                ip=client_ip,
                headers=request_headers,
                client_device_context=device_context,
            )

        body = build_evaluate_envelope(
            tenant_id=tenant_id,
            event_type=event_type,
            entity_id=entity_id,
            payload=payload,
            session_id=session_id,
            metadata=metadata,
            device_context=device_context,
            region=region,
            challenge_policy_id=challenge_policy_id,
        )
        body_bytes = canonical_json_bytes(body)
        nonce = client_nonce
        ts = client_timestamp
        if replay_safe_headers:
            if nonce is None:
                nonce = default_client_nonce()
            if ts is None:
                ts = default_client_timestamp()
        headers = build_evaluate_request_headers(
            api_key=self._api_key,
            body_bytes=body_bytes,
            request_secret=self._request_signing_secret,
            idempotency_key=idempotency_key,
            client_nonce=nonce,
            client_timestamp=ts,
        )

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                f"{self._base}/v1/decisions/evaluate",
                content=body_bytes,
                headers=headers,
            )
            r.raise_for_status()
            data = r.json()
            if self._strict_evaluate_response:
                from fraud_stack_sdk.evaluate_response import parse_evaluate_response

                return parse_evaluate_response(data)
            return data

    def validate_attestation(self, nonce: str, token: str, provider: str) -> dict[str, Any]:
        with httpx.Client(timeout=self._timeout) as client:
            r = client.post(
                f"{self._base}/v1/attestation/verify",
                json={"nonce": nonce, "token": token, "provider": provider},
                headers=self._headers(),
            )
            r.raise_for_status()
            return r.json()

    def get_audit(self, trace_id: UUID | str, tenant_id: str) -> dict[str, Any]:
        tid = str(trace_id)
        with httpx.Client(timeout=self._timeout) as client:
            r = client.get(
                f"{self._base}/v1/audit/{tid}",
                params={"tenant_id": tenant_id},
                headers=self._headers(),
            )
            r.raise_for_status()
            return r.json()
