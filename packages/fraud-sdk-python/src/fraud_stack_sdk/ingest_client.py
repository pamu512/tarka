from __future__ import annotations

import math
from datetime import datetime, timezone
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


# Unix seconds are below this. Larger numbers are epoch milliseconds (Date.now()).
_EPOCH_MS_MIN = 1_000_000_000_000


def mandate_expired(value: Any, now: datetime | None = None) -> bool:
    """True when expiry is missing-as-invalid, unparseable, or at/before ``now``.

    Numbers below 1e12 are Unix seconds. Numbers at or above 1e12 are epoch
    milliseconds, matching the TypeScript client. A past millisecond timestamp
    stays out of mandate.
    """
    clock = now or datetime.now(timezone.utc)
    if isinstance(value, bool) or value is None:
        return True
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return True
        seconds = float(value)
        if seconds >= _EPOCH_MS_MIN:
            seconds /= 1000.0
        try:
            parsed = datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return True
        return parsed <= clock
    if not isinstance(value, str) or not value.strip():
        return True
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed <= clock


def apply_agent_mandate(event: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Copy ``event``. Absent ``actor_kind`` stays absent. No score or decision is added.

    ``actor_kind`` matching ``agent`` in any case is stored as ``agent``. Empty
    caps omit ``mandate_caps``. A past or unparseable ``mandate_expires_at``
    sets ``mandate_expired`` true.
    """
    out = dict(event)
    kind = out.get("actor_kind")
    missing_actor = "actor_kind" not in out or not isinstance(kind, str) or not kind.strip()
    if missing_actor:
        out.pop("actor_kind", None)
        out.pop("mandate_caps", None)
        out.pop("mandate_expires_at", None)
        out.pop("mandate_expired", None)
        return out
    norm = kind.strip()
    if norm.lower() == "agent":
        norm = "agent"
    else:
        out["actor_kind"] = norm
        return out
    out["actor_kind"] = "agent"
    caps = out.get("mandate_caps")
    if "mandate_caps" not in event or not isinstance(caps, dict) or len(caps) == 0:
        out.pop("mandate_caps", None)
    expires = out.get("mandate_expires_at")
    if "mandate_expires_at" not in event or expires is None or (
        isinstance(expires, str) and not expires.strip()
    ):
        out.pop("mandate_expires_at", None)
        out.pop("mandate_expired", None)
        return out
    if mandate_expired(expires, now):
        out["mandate_expired"] = True
    else:
        out.pop("mandate_expired", None)
    return out


def compose_ingest_event(
    tenant_id: str,
    event_type: str,
    entity_id: str,
    *,
    session_id: str | None = None,
    payload: dict[str, Any] | None = None,
    device_context: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    actor_kind: str | None = None,
    mandate_caps: dict[str, Any] | None = None,
    mandate_expires_at: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
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
    if actor_kind is not None:
        body["actor_kind"] = actor_kind
    if mandate_caps is not None:
        body["mandate_caps"] = mandate_caps
    if mandate_expires_at is not None:
        body["mandate_expires_at"] = mandate_expires_at
    return apply_agent_mandate(body, now=now)


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
        actor_kind: str | None = None,
        mandate_caps: dict[str, Any] | None = None,
        mandate_expires_at: str | None = None,
    ) -> IngestEventResponse:
        body = compose_ingest_event(
            tenant_id,
            event_type,
            entity_id,
            session_id=session_id,
            payload=payload,
            device_context=device_context,
            metadata=metadata,
            actor_kind=actor_kind,
            mandate_caps=mandate_caps,
            mandate_expires_at=mandate_expires_at,
        )

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
        actor_kind: str | None = None,
        mandate_caps: dict[str, Any] | None = None,
        mandate_expires_at: str | None = None,
    ) -> IngestEventResponse:
        body = compose_ingest_event(
            tenant_id,
            event_type,
            entity_id,
            session_id=session_id,
            payload=payload,
            device_context=device_context,
            metadata=metadata,
            actor_kind=actor_kind,
            mandate_caps=mandate_caps,
            mandate_expires_at=mandate_expires_at,
        )

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
        normalized = [apply_agent_mandate(e) if isinstance(e, dict) else e for e in events]
        with httpx.Client(timeout=self._timeout) as client:
            r = client.post(
                f"{self._base}/v1/events/batch",
                json={"events": normalized},
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
        normalized = [apply_agent_mandate(e) if isinstance(e, dict) else e for e in events]
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                f"{self._base}/v1/events/batch",
                json={"events": normalized},
                headers=headers,
            )
            r.raise_for_status()
            return r.json()
