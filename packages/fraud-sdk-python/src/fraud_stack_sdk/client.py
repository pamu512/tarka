from __future__ import annotations

from typing import Any, TypedDict
from uuid import UUID

import httpx

from fraud_stack_sdk.signals import ServerSignalCollector


class InferenceContext(TypedDict):
    integrity_confidence: float
    tamper_risk: float
    network_trust: float
    replay_risk: float
    geo_consistency_risk: float
    top_signals: list[str]


class EvaluateResponse(TypedDict, total=False):
    trace_id: str
    decision: str
    score: float
    tags: list[str]
    rule_hits: list[str]
    reasons: list[str]
    ml_score: float | None
    inference_context: InferenceContext


class DecisionClient:
    """Thin client for Decision API with optional server-side signal collection."""

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        timeout: float = 10.0,
        server_signals: bool = False,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._collector = ServerSignalCollector() if server_signals else None

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
    ) -> EvaluateResponse:
        if self._collector and client_ip:
            device_context = self._collector.build_device_context(
                ip=client_ip,
                headers=request_headers,
                client_device_context=device_context,
            )

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

        with httpx.Client(timeout=self._timeout) as client:
            r = client.post(
                f"{self._base}/v1/decisions/evaluate",
                json=body,
                headers=self._headers(),
            )
            r.raise_for_status()
            return r.json()

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
    ) -> EvaluateResponse:
        if self._collector and client_ip:
            device_context = self._collector.build_device_context(
                ip=client_ip,
                headers=request_headers,
                client_device_context=device_context,
            )

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

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                f"{self._base}/v1/decisions/evaluate",
                json=body,
                headers=self._headers(),
            )
            r.raise_for_status()
            return r.json()

    def validate_attestation(self, nonce: str, token: str, provider: str) -> dict[str, Any]:
        with httpx.Client(timeout=self._timeout) as client:
            r = client.post(
                f"{self._base}/v1/attestation/verify",
                json={"nonce": nonce, "token": token, "provider": provider},
                headers=self._headers(),
            )
            r.raise_for_status()
            return r.json()

    def get_audit(self, trace_id: UUID | str) -> dict[str, Any]:
        tid = str(trace_id)
        with httpx.Client(timeout=self._timeout) as client:
            r = client.get(f"{self._base}/v1/audit/{tid}", headers=self._headers())
            r.raise_for_status()
            return r.json()
