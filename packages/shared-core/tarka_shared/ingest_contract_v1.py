"""Ingest Contract v1 — shared envelope field checks.

Canonical public async ingest is event-ingest ``POST /v1/events`` (flat or
``schema_version: "1"`` envelope). Orchestrator ``POST /v1/ingest`` is a
transaction-policy adapter (``TransactionSchema``) that must map into the same
semantic fields before scoring.

See ``docs/docs/guides/ingest-contract-v1.md``.
"""

from __future__ import annotations

from typing import Any

# Keep aligned with decision_api.schemas.EventType / event_ingest.ingest_contract
VALID_EVENT_TYPES = frozenset(
    {"login", "payment", "signup", "device", "session", "custom"}
)

REQUIRED_ENVELOPE_FIELDS = ("tenant_id", "entity_id", "event_type")


class IngestContractV1Error(Exception):
    """Envelope violates Ingest Contract v1 required fields."""

    def __init__(self, reason_codes: list[str], message: str) -> None:
        self.reason_codes = reason_codes
        self.message = message
        super().__init__(message)


def validate_required_envelope_fields(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize and validate the three required evaluate/ingest identity fields.

    Does not unwrap ``schema_version`` envelopes — callers (event-ingest) do that
    first. Returns a shallow copy with stripped string fields.
    """
    if not isinstance(raw, dict):
        raise IngestContractV1Error(
            ["ingest_body_not_object"],
            "ingest body must be a JSON object",
        )
    out = dict(raw)
    tid = out.get("tenant_id")
    eid = out.get("entity_id")
    et = out.get("event_type")

    if tid is None or (isinstance(tid, str) and not tid.strip()):
        raise IngestContractV1Error(
            ["ingest_tenant_id_empty"],
            "tenant_id is required and must be non-empty",
        )
    if eid is None or (isinstance(eid, str) and not eid.strip()):
        raise IngestContractV1Error(
            ["ingest_entity_id_empty"],
            "entity_id is required and must be non-empty",
        )
    if et is None or (isinstance(et, str) and not str(et).strip()):
        raise IngestContractV1Error(
            ["ingest_event_type_empty"],
            "event_type is required and must be non-empty",
        )

    et_s = str(et).strip()
    if et_s not in VALID_EVENT_TYPES:
        raise IngestContractV1Error(
            ["ingest_event_type_invalid"],
            f"event_type {et_s!r} is not a valid enum value",
        )

    out["tenant_id"] = str(tid).strip()
    out["entity_id"] = str(eid).strip()
    out["event_type"] = et_s
    return out
