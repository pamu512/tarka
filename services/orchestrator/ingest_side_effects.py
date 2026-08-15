"""Shared audit + outbox commit after evaluate (sync ingest and async consumer)."""

from __future__ import annotations

import hmac
import logging
import os
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Request, status
from pydantic import BaseModel, Field

from audit_case_worker import persist_orchestrator_audit_log
from database import TarkaDatabaseException, atomic_transaction
from enforcement.log_decision import persist_lekh_decision
from models.outbox import (
    OUTBOX_EVENT_GRAPH_INGEST,
    OUTBOX_EVENT_VELOCITY_UPDATE,
    OutboxDAO,
)
from tarka_shared.audit_errors import AuditPersistenceError

logger = logging.getLogger(__name__)


class IngestSideEffectsRequest(BaseModel):
    event: dict[str, Any]
    rule_data: dict[str, Any] = Field(default_factory=dict)
    actions: list[str] = Field(default_factory=list)


def require_internal_ingest_auth(request: Request) -> None:
    expected = (os.environ.get("ORCHESTRATOR_INTERNAL_SECRET") or "").strip()
    if not expected:
        return
    got = (request.headers.get("x-internal-secret") or "").strip()
    if not got or not hmac.compare_digest(got, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_internal_secret")


def _graph_payload_from_event(
    *,
    event: dict[str, Any],
    rule_data: dict[str, Any],
    audit_log_id: int,
) -> dict[str, Any]:
    entity_id = str(event.get("entity_id") or "")
    transaction_id = str(rule_data.get("transaction_id") or entity_id)
    return {
        "schema": "tarka.graph_ingest.v1",
        "transaction_id": transaction_id,
        "entity_id": entity_id,
        "audit_log_id": audit_log_id,
        "resolved_rules": {},
        "blocking_rule_id": rule_data.get("blocking_rule_id"),
        "event": event,
    }


def _velocity_payload_from_event(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    meta = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    entity_id = str(event.get("entity_id") or "")
    amount = payload.get("amount")
    try:
        amount_cents = int(round(float(amount) * 100)) if amount is not None else 0
    except (TypeError, ValueError):
        amount_cents = 0
    if amount_cents < 0:
        amount_cents = 0
    ts_raw = payload.get("timestamp")
    if hasattr(ts_raw, "isoformat"):
        ts = ts_raw.isoformat()
    elif isinstance(ts_raw, str) and ts_raw.strip():
        ts = ts_raw.strip()
    else:
        ts = datetime.now(tz=UTC).isoformat()
    return {
        "schema": "tarka.velocity_update.v1",
        "entity_id": entity_id,
        "device_hash_string": None,
        "client_browser_metadata_context": {
            k: meta[k]
            for k in ("ip", "ip_address", "tenant_id", "canvas_fingerprint")
            if k in meta
        }
        or None,
        "amount_cents": amount_cents,
        "transaction_timestamp_utc": ts,
    }


async def commit_evaluate_side_effects(
    session_factory: Any,
    *,
    event: dict[str, Any],
    rule_data: dict[str, Any],
    actions: list[str],
) -> int:
    """Persist lekh + audit + GRAPH_INGEST + VELOCITY_UPDATE. Returns audit_log_id."""
    if session_factory is None:
        raise AuditPersistenceError.unconfigured()
    entity_id = str(event.get("entity_id") or "").strip()
    if not entity_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "ingest_entity_id_empty"},
        )
    meta = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    async with atomic_transaction(session_factory) as session:
        await persist_lekh_decision(session, entity_id=entity_id, rule_data=rule_data)
        audit_log_id = await persist_orchestrator_audit_log(
            session,
            entity_id=entity_id,
            metadata=dict(meta),
            actions=actions,
            rule_data=rule_data,
            shadow_data=None,
            shadow_matches=[],
            transaction_envelope=event,
        )
        await OutboxDAO.create_task(
            session,
            OUTBOX_EVENT_GRAPH_INGEST,
            f"graph_ingest:{entity_id}:{audit_log_id}",
            _graph_payload_from_event(event=event, rule_data=rule_data, audit_log_id=audit_log_id),
        )
        await OutboxDAO.create_task(
            session,
            OUTBOX_EVENT_VELOCITY_UPDATE,
            f"velocity_update:{entity_id}:{audit_log_id}",
            _velocity_payload_from_event(event),
        )
    return audit_log_id


def _raise_side_effect_http(exc: AuditPersistenceError) -> None:
    raise HTTPException(
        status_code=exc.http_status,
        detail={
            "error": exc.error_code,
            "message": exc.message,
            **({"entity_id": exc.entity_id} if exc.entity_id else {}),
        },
    ) from exc


async def handle_ingest_side_effects_request(
    request: Request,
    body: IngestSideEffectsRequest,
) -> dict[str, Any]:
    require_internal_ingest_auth(request)
    fac = getattr(request.app.state, "audit_session_factory", None)
    entity_id = str(body.event.get("entity_id") or "").strip()
    try:
        audit_log_id = await commit_evaluate_side_effects(
            fac,
            event=body.event,
            rule_data=body.rule_data,
            actions=[str(a) for a in body.actions],
        )
    except HTTPException:
        raise
    except AuditPersistenceError as exc:
        _raise_side_effect_http(exc)
    except TarkaDatabaseException as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": exc.error_code,
                "message": exc.message,
                "entity_id": entity_id,
            },
        ) from exc
    except Exception:
        logger.exception("ingest_side_effects_failed entity_id=%s", entity_id)
        _raise_side_effect_http(
            AuditPersistenceError.persist_failed(entity_id=entity_id, component="orchestrator"),
        )
    return {"ok": True, "audit_log_id": audit_log_id}
