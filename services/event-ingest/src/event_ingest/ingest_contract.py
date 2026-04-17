"""Contract-first ingest envelope (v1.2.5 / E1) — versioned wrapper + reason codes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

# Align with Decision API `EventType` enum.
ALLOWED_EVENT_TYPES = frozenset({"login", "payment", "signup", "device", "session", "custom"})


class IngestEventInner(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=256)
    event_type: str = Field(..., min_length=1, max_length=64)
    entity_id: str = Field(..., min_length=1, max_length=512)
    session_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    device_context: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestEnvelopeV1(BaseModel):
    schema_version: Literal["1"]
    event: IngestEventInner


def parse_ingest_body(
    raw: Any,
    *,
    envelope_mode: str,
) -> IngestEventInner:
    """Parse flat or v1 envelope body. Raises ValueError(reason_code) for HTTP 422 mapping."""
    mode = (envelope_mode or "optional").strip().lower()
    if not isinstance(raw, dict):
        raise ValueError("ingest_body_not_object")

    if mode == "required":
        if raw.get("schema_version") != "1" or "event" not in raw:
            raise ValueError("ingest_schema_required")
        try:
            env = IngestEnvelopeV1.model_validate(raw)
        except ValidationError:
            raise ValueError("ingest_envelope_invalid") from None
        inner = env.event
    else:
        if raw.get("schema_version") == "1" and "event" in raw:
            try:
                env = IngestEnvelopeV1.model_validate(raw)
                inner = env.event
            except ValidationError:
                raise ValueError("ingest_envelope_invalid") from None
        else:
            if raw.get("schema_version") not in (None, ""):
                raise ValueError("ingest_schema_unknown")
            try:
                inner = IngestEventInner.model_validate(raw)
            except ValidationError:
                raise ValueError("ingest_event_invalid") from None

    et = str(inner.event_type).strip().lower()
    if et not in ALLOWED_EVENT_TYPES:
        raise ValueError("ingest_event_type_invalid")

    return inner
