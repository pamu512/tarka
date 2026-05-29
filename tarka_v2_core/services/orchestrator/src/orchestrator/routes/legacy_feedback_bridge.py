"""Deprecated legacy feedback endpoints bridged to ``POST /v1/operational-signals``."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from orchestrator.openapi_schemas import AiFeedbackRequest
from orchestrator.schemas.operational_signals import (
    ManualOverrideAction,
    OperationalSignalCreate,
    SignalType,
)
from orchestrator.services.operational_signal_ingress import submit_operational_signal

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Legacy feedback (deprecated)"])

_LEGACY_SUNSET = "Sat, 30 Aug 2026 23:59:59 GMT"
_SUCCESSOR_PATH = "/v1/operational-signals"
_REASON_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,31}$")
_OPERATOR_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:@/+-]{0,127}$")
_ENTITY_UUID_NAMESPACE = NAMESPACE_URL


class LegacyBridgeError(ValueError):
    """Raised when a legacy payload cannot be mapped to ``OperationalSignalCreate``."""


class ConsortiumFeedbackRequest(BaseModel):
    """Legacy ``POST /v1/consortium/feedback`` body (decision-api compatible)."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=128)
    entity_id: str = Field(min_length=1, max_length=512)
    outcome: str = Field(pattern=r"^(false_positive|confirmed_fraud)$")
    ttl_days: int = Field(default=30, ge=1, le=365)
    consortium_id: str | None = Field(default=None, max_length=128)


class CopilotFeedbackRequest(BaseModel):
    """Legacy ``POST /v1/feedback`` body (investigation-agent copilot compatible)."""

    model_config = ConfigDict(extra="forbid")

    turn_id: str = Field(..., min_length=1, max_length=80)
    rating: int = Field(..., ge=-1, le=1, description="-1 down, 0 neutral, 1 up")
    note: str | None = Field(default=None, max_length=2000)
    claim_indices: list[int] | None = None
    tenant_id: str | None = Field(default=None, max_length=128)
    analyst_id: str | None = Field(default=None, max_length=128)
    tags: dict[str, Any] | None = None
    entity_id: str | None = Field(
        default=None,
        max_length=128,
        description="Optional subject entity; when omitted a stable UUID is derived from turn_id.",
    )


def _deprecation_headers() -> dict[str, str]:
    return {
        "Deprecation": "true",
        "Sunset": _LEGACY_SUNSET,
        "Link": f'<{_SUCCESSOR_PATH}>; rel="successor-version"',
        "X-Tarka-Legacy-Bridge": "operational-signals",
    }


def _attach_deprecation(response: Response) -> None:
    for key, value in _deprecation_headers().items():
        response.headers[key] = value


def _normalize_operator_id(raw: str | None, *, fallback: str) -> str:
    token = (raw or "").strip() or fallback.strip()
    if not _OPERATOR_ID_RE.fullmatch(token):
        raise LegacyBridgeError(f"operator identifier {token!r} has invalid shape")
    return token


def _normalize_reason_code(raw: str) -> str:
    token = raw.strip().upper()
    if not _REASON_CODE_RE.fullmatch(token):
        raise LegacyBridgeError(f"reason_code {token!r} has invalid shape")
    return token


def _entity_uuid_from_legacy(raw: str | None, *, seed: str) -> UUID:
    token = (raw or "").strip()
    if token:
        try:
            return UUID(token)
        except ValueError:
            pass
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return UUID(digest[:32])
    seed_token = seed.strip()
    if not seed_token:
        raise LegacyBridgeError("cannot derive target_entity_id without entity_id or seed")
    return uuid5(_ENTITY_UUID_NAMESPACE, f"tarka:legacy_feedback:{seed_token}")


def _stable_idempotency_key(prefix: str, *parts: str) -> str:
    joined = "|".join(p.strip() for p in parts if p and p.strip())
    if not joined:
        joined = str(uuid4())
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:32]
    return f"{prefix}:{digest}"


def ai_feedback_to_operational_signal(body: AiFeedbackRequest) -> OperationalSignalCreate:
    """Map ``POST /v1/ai/feedback`` payloads to ``MANUAL_OVERRIDE`` operational signals."""
    reasons = list(body.rejection_reasons)
    seed = body.trace_id or body.entity_id or reasons[0]
    target_entity_id = _entity_uuid_from_legacy(body.entity_id, seed=seed)
    analyst_id = _normalize_operator_id(body.source or body.tenant_id, fallback="ai_feedback")
    notes_parts: list[str] = [f"rejection_reasons={json.dumps(reasons, ensure_ascii=False)}"]
    if body.context:
        notes_parts.append(f"context={body.context.strip()}")
    if body.trace_id:
        notes_parts.append(f"trace_id={body.trace_id.strip()}")
    if body.tenant_id:
        notes_parts.append(f"tenant_id={body.tenant_id.strip()}")

    return OperationalSignalCreate.model_validate(
        {
            "idempotency_key": _stable_idempotency_key(
                "legacy:ai_feedback",
                body.trace_id or "",
                body.entity_id or "",
                "|".join(reasons),
            ),
            "target_entity_id": str(target_entity_id),
            "signal_type": SignalType.MANUAL_OVERRIDE.value,
            "metadata": {
                "override_action": ManualOverrideAction.REVIEW.value,
                "reason_code": _normalize_reason_code("AI_REJECTION"),
                "analyst_id": analyst_id,
                "prior_decision": "SHADOW_LLM",
                "notes": "\n".join(notes_parts)[:4096],
            },
        },
    )


def consortium_feedback_to_operational_signal(
    body: ConsortiumFeedbackRequest,
) -> OperationalSignalCreate:
    """Map ``POST /v1/consortium/feedback`` payloads to ``MANUAL_OVERRIDE`` operational signals."""
    outcome = body.outcome.strip().lower()
    if outcome == "false_positive":
        override_action = ManualOverrideAction.REVIEW
        reason_code = "FALSE_POSITIVE"
    elif outcome == "confirmed_fraud":
        override_action = ManualOverrideAction.BLOCK
        reason_code = "CONFIRMED_FRAUD"
    else:
        raise LegacyBridgeError(f"unsupported consortium outcome: {body.outcome!r}")

    target_entity_id = _entity_uuid_from_legacy(
        body.entity_id,
        seed=f"{body.tenant_id}:{body.entity_id}",
    )
    analyst_id = _normalize_operator_id(body.tenant_id, fallback="consortium_feedback")
    notes = (
        f"consortium_outcome={outcome}; consortium_id={(body.consortium_id or 'default').strip()}; "
        f"ttl_days={body.ttl_days}; legacy_entity_id={body.entity_id.strip()}"
    )

    return OperationalSignalCreate.model_validate(
        {
            "idempotency_key": _stable_idempotency_key(
                "legacy:consortium_feedback",
                body.tenant_id,
                body.entity_id,
                outcome,
                body.consortium_id or "",
            ),
            "target_entity_id": str(target_entity_id),
            "signal_type": SignalType.MANUAL_OVERRIDE.value,
            "metadata": {
                "override_action": override_action.value,
                "reason_code": _normalize_reason_code(reason_code),
                "analyst_id": analyst_id,
                "prior_decision": "CONSORTIUM_SIGNAL",
                "notes": notes[:4096],
            },
        },
    )


def copilot_feedback_to_operational_signal(body: CopilotFeedbackRequest) -> OperationalSignalCreate:
    """Map ``POST /v1/feedback`` copilot payloads to ``MANUAL_OVERRIDE`` operational signals."""
    if body.rating > 0:
        override_action = ManualOverrideAction.ALLOW
        reason_code = "COPILOT_UPVOTE"
    elif body.rating < 0:
        override_action = ManualOverrideAction.FLAG
        reason_code = "COPILOT_DOWNVOTE"
    else:
        override_action = ManualOverrideAction.REVIEW
        reason_code = "COPILOT_NEUTRAL"

    if not (body.analyst_id or "").strip() and not (body.turn_id or "").strip():
        raise LegacyBridgeError("turn_id is required for legacy copilot feedback bridge")

    analyst_id = _normalize_operator_id(
        body.analyst_id,
        fallback=f"copilot:{body.turn_id.strip()}",
    )
    target_entity_id = _entity_uuid_from_legacy(
        body.entity_id,
        seed=f"turn:{body.turn_id.strip()}",
    )

    notes_parts = [f"turn_id={body.turn_id.strip()}", f"rating={body.rating}"]
    if body.note:
        notes_parts.append(f"note={body.note.strip()}")
    if body.claim_indices:
        notes_parts.append(f"claim_indices={body.claim_indices}")
    if body.tags:
        notes_parts.append(f"tags={json.dumps(body.tags, ensure_ascii=False, sort_keys=True)}")
    if body.tenant_id:
        notes_parts.append(f"tenant_id={body.tenant_id.strip()}")

    return OperationalSignalCreate.model_validate(
        {
            "idempotency_key": _stable_idempotency_key(
                "legacy:copilot_feedback",
                body.turn_id,
                str(body.rating),
                body.analyst_id or "",
            ),
            "target_entity_id": str(target_entity_id),
            "signal_type": SignalType.MANUAL_OVERRIDE.value,
            "metadata": {
                "override_action": override_action.value,
                "reason_code": _normalize_reason_code(reason_code),
                "analyst_id": analyst_id,
                "prior_decision": "COPILOT_TURN",
                "notes": "\n".join(notes_parts)[:4096],
            },
        },
    )


async def _bridge_legacy_payload(
    request: Request,
    response: Response,
    *,
    legacy_route: str,
    mapped: OperationalSignalCreate,
) -> dict[str, Any]:
    _attach_deprecation(response)
    try:
        accepted = await submit_operational_signal(request, mapped)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("legacy_feedback_bridge_failed route=%s", legacy_route)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="legacy feedback bridge failed to submit operational signal",
        ) from exc

    event_id = str(accepted.event_id)
    logger.info(
        "legacy_feedback_bridged route=%s event_id=%s signal_type=%s successor=%s",
        legacy_route,
        event_id,
        mapped.signal_type.value,
        _SUCCESSOR_PATH,
    )
    return {
        "ok": True,
        "stored": True,
        "deprecated": True,
        "successor": _SUCCESSOR_PATH,
        "event_id": event_id,
        "status": accepted.status,
    }


@router.post(
    "/ai/feedback",
    status_code=status.HTTP_202_ACCEPTED,
    summary="[Deprecated] Record AI rejection feedback",
    deprecated=True,
    description=(
        "Deprecated — transforms the legacy AI feedback payload into "
        "``OperationalSignalCreate`` and forwards to ``POST /v1/operational-signals``. "
        "Use ``POST /v1/operational-signals`` with ``signal_type=MANUAL_OVERRIDE`` directly."
    ),
)
async def legacy_ai_feedback(
    request: Request,
    response: Response,
    body: AiFeedbackRequest,
) -> dict[str, Any]:
    try:
        mapped = ai_feedback_to_operational_signal(body)
    except LegacyBridgeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    payload = await _bridge_legacy_payload(
        request,
        response,
        legacy_route="/v1/ai/feedback",
        mapped=mapped,
    )
    payload["feedback_id"] = payload["event_id"]
    return payload


@router.post(
    "/consortium/feedback",
    status_code=status.HTTP_202_ACCEPTED,
    summary="[Deprecated] Consortium outcome feedback",
    deprecated=True,
    description=(
        "Deprecated — maps consortium ``false_positive`` / ``confirmed_fraud`` outcomes to "
        "``MANUAL_OVERRIDE`` operational signals and forwards to ``POST /v1/operational-signals``."
    ),
)
async def legacy_consortium_feedback(
    request: Request,
    response: Response,
    body: ConsortiumFeedbackRequest,
) -> dict[str, Any]:
    try:
        mapped = consortium_feedback_to_operational_signal(body)
    except LegacyBridgeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    payload = await _bridge_legacy_payload(
        request,
        response,
        legacy_route="/v1/consortium/feedback",
        mapped=mapped,
    )
    payload["signal_hash"] = _stable_idempotency_key(
        "legacy:consortium_signal_hash",
        body.tenant_id,
        body.entity_id,
    )
    return payload


@router.post(
    "/feedback",
    status_code=status.HTTP_202_ACCEPTED,
    summary="[Deprecated] Copilot turn feedback",
    deprecated=True,
    description=(
        "Deprecated — maps investigation-agent copilot turn feedback to "
        "``MANUAL_OVERRIDE`` operational signals and forwards to ``POST /v1/operational-signals``."
    ),
)
async def legacy_copilot_feedback(
    request: Request,
    response: Response,
    body: CopilotFeedbackRequest,
) -> dict[str, Any]:
    try:
        mapped = copilot_feedback_to_operational_signal(body)
    except LegacyBridgeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    payload = await _bridge_legacy_payload(
        request,
        response,
        legacy_route="/v1/feedback",
        mapped=mapped,
    )
    payload["feedback_id"] = payload["event_id"]
    return payload
