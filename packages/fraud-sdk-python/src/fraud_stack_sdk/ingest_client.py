from __future__ import annotations

from typing import Any, NotRequired, TypedDict

import httpx


class IngestEventResponse(TypedDict):
    accepted: bool
    stream_seq: int
    ingest_id: str
    duplicate: NotRequired[bool]


class IngestBatchResultItem(TypedDict):
    ingest_id: str
    seq: int


class IngestBatchResponse(TypedDict):
    accepted: int
    results: list[IngestBatchResultItem]
    duplicate: NotRequired[bool]


class EventIngestClient:
    """Client for the Event Ingest service (NATS-backed async path to Decision API)."""

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        timeout: float = 10.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            h["X-API-Key"] = self._api_key
        return h

    def send_event(
        self,
        tenant_id: str,
        event_type: str,
        entity_id: str,
        *,
        session_id: str | None = None,
        payload: dict[str, Any] | None = None,
        device_context: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> IngestEventResponse:
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

        headers = self._headers()
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        with httpx.Client(timeout=self._timeout) as client:
            r = client.post(
                f"{self._base}/v1/events",
                json=body,
                headers=headers,
            )
            r.raise_for_status()
            return r.json()

    async def send_event_async(
        self,
        tenant_id: str,
        event_type: str,
        entity_id: str,
        *,
        session_id: str | None = None,
        payload: dict[str, Any] | None = None,
        device_context: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> IngestEventResponse:
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

        headers = self._headers()
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                f"{self._base}/v1/events",
                json=body,
                headers=headers,
            )
            r.raise_for_status()
            return r.json()

    def send_batch(
        self,
        events: list[dict[str, Any]],
        *,
        idempotency_key: str | None = None,
    ) -> IngestBatchResponse:
        headers = self._headers()
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        with httpx.Client(timeout=self._timeout) as client:
            r = client.post(
                f"{self._base}/v1/events/batch",
                json={"events": events},
                headers=headers,
            )
            r.raise_for_status()
            return r.json()

    async def send_batch_async(
        self,
        events: list[dict[str, Any]],
        *,
        idempotency_key: str | None = None,
    ) -> IngestBatchResponse:
        headers = self._headers()
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                f"{self._base}/v1/events/batch",
                json={"events": events},
                headers=headers,
            )
            r.raise_for_status()
            return r.json()
