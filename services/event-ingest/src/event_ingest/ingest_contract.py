"""Contract-first single/batch event body parsing (v1.2.5 E1).

Supports optional v1 envelope ``{ "schema_version": "1", "event": { ... } }`` and validates
``event_type`` against Decision API enum. See ``INGEST_ENVELOPE_MODE`` and
``INGEST_REQUIRE_IDEMPOTENCY_KEY`` in config.
"""

from __future__ import annotations

from typing import Any

# Keep aligned with decision_api.schemas.EventType
VALID_EVENT_TYPES = frozenset({"login", "payment", "signup", "device", "session", "custom"})


class IngestContractError(Exception):
    """Raised when the HTTP body violates the ingest contract."""

    def __init__(self, reason_codes: list[str], message: str) -> None:
        self.reason_codes = reason_codes
        self.message = message
        super().__init__(message)


def _strip_event_dict(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if not k.startswith("_")}


def _unwrap_envelope(
    raw: dict[str, Any],
    *,
    envelope_mode: str,
) -> dict[str, Any]:
    """Return a flat event dict or raise IngestContractError."""
    sv = raw.get("schema_version")
    if sv is None or sv == "":
        if envelope_mode == "required":
            raise IngestContractError(
                ["ingest_envelope_required"],
                'Set schema_version to "1" and nest the payload under "event", or set INGEST_ENVELOPE_MODE=optional.',
            )
        return _strip_event_dict(raw)

    if str(sv) != "1":
        raise IngestContractError(
            ["ingest_envelope_version_unsupported"],
            f'Unsupported schema_version {sv!r}; only "1" is accepted.',
        )

    inner = raw.get("event")
    if not isinstance(inner, dict):
        raise IngestContractError(
            ["ingest_envelope_event_missing"],
            'When schema_version is "1", a JSON object "event" is required.',
        )
    return _strip_event_dict(inner)


def parse_ingest_event_body(
    raw: dict[str, Any],
    *,
    envelope_mode: str,
) -> dict[str, Any]:
    """
    Normalize to a flat event dict suitable for ``EventPayload.model_validate``.

    Raises ``IngestContractError`` with ``reason_codes`` on violation.
    """
    flat = _unwrap_envelope(raw, envelope_mode=envelope_mode)
    tid = flat.get("tenant_id")
    eid = flat.get("entity_id")
    et = flat.get("event_type")

    if tid is None or (isinstance(tid, str) and not tid.strip()):
        raise IngestContractError(["ingest_tenant_id_empty"], "tenant_id is required and must be non-empty.")
    if eid is None or (isinstance(eid, str) and not eid.strip()):
        raise IngestContractError(["ingest_entity_id_empty"], "entity_id is required and must be non-empty.")
    if et is None or (isinstance(et, str) and not str(et).strip()):
        raise IngestContractError(["ingest_event_type_empty"], "event_type is required and must be non-empty.")

    et_s = str(et).strip()
    if et_s not in VALID_EVENT_TYPES:
        raise IngestContractError(
            ["ingest_event_type_invalid"],
            f"event_type {et_s!r} is not a valid enum value.",
        )

    out = dict(flat)
    out["tenant_id"] = str(tid).strip()
    out["entity_id"] = str(eid).strip()
    out["event_type"] = et_s
    return out


def parse_batch_event_item(
    raw_item: dict[str, Any],
    *,
    envelope_mode: str,
) -> dict[str, Any]:
    """Parse one element of ``events[]`` (may be flat or v1 envelope)."""
    return parse_ingest_event_body(raw_item, envelope_mode=envelope_mode)
