"""Ingest Contract v1 — shared envelope field checks.

Canonical public async ingest is event-ingest ``POST /v1/events`` (flat or
``schema_version: "1"`` envelope). Orchestrator ``POST /v1/ingest`` is a
transaction-policy adapter (``TransactionSchema``) that must map into the same
semantic fields before scoring.

See ``docs/docs/guides/ingest-contract-v1.md``.
"""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)

# Literal frozenset — schema_registry_compat.py parses this AST. Seed six only.
VALID_EVENT_TYPES = frozenset(
    {"login", "payment", "signup", "device", "session", "custom"}
)
SEED_EVENT_TYPES = VALID_EVENT_TYPES
EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")

REQUIRED_ENVELOPE_FIELDS = ("tenant_id", "entity_id", "event_type")

_env_bad_logged = False


def validate_event_type_shape(name: Any) -> str:
    stripped = "" if name is None else str(name).strip()
    if not stripped:
        raise ValueError("event_type must not be empty")
    if not EVENT_TYPE_RE.fullmatch(stripped):
        raise ValueError(f"invalid event_type: {stripped!r}")
    return stripped


def parse_env_event_types(raw: str | None) -> frozenset[str]:
    """Parse TARKA_EVENT_TYPES. Garbage tokens skipped (log once)."""
    global _env_bad_logged
    if raw is None or not str(raw).strip():
        return frozenset()
    out: set[str] = set()
    bad = False
    for part in str(raw).split(","):
        token = part.strip()
        if not token:
            continue
        try:
            out.add(validate_event_type_shape(token))
        except ValueError:
            bad = True
    if bad and not _env_bad_logged:
        log.warning("TARKA_EVENT_TYPES skipped invalid token(s) in %r", raw)
        _env_bad_logged = True
    return frozenset(out)


def allowed_event_types(
    overlay: frozenset[str] | None = None,
    env: frozenset[str] | None = None,
) -> frozenset[str]:
    extra: set[str] = set()
    for name in overlay or ():
        try:
            extra.add(validate_event_type_shape(name))
        except ValueError:
            continue
    extra |= set(env or ())
    return SEED_EVENT_TYPES | frozenset(extra)


class IngestContractV1Error(Exception):
    """Envelope violates Ingest Contract v1 required fields."""

    def __init__(self, reason_codes: list[str], message: str) -> None:
        self.reason_codes = reason_codes
        self.message = message
        super().__init__(message)


def validate_required_envelope_fields(
    raw: dict[str, Any],
    allowed: frozenset[str] | None = None,
) -> dict[str, Any]:
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

    try:
        et_s = validate_event_type_shape(et)
    except ValueError:
        raise IngestContractV1Error(
            ["ingest_event_type_invalid"],
            f"event_type {et!r} is not a valid name",
        ) from None
    allow = allowed if allowed is not None else SEED_EVENT_TYPES
    if et_s not in allow:
        raise IngestContractV1Error(
            ["ingest_event_type_invalid"],
            f"event_type {et_s!r} is not on the allow-list",
        )

    out["tenant_id"] = str(tid).strip()
    out["entity_id"] = str(eid).strip()
    out["event_type"] = et_s
    return out
