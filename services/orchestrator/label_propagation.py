"""Outbox enqueue + evidence/disposition helpers for ``normalized_labels`` propagation."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from ingestor.manifest_schema import TransactionSchema
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tarka_shared.audit_trail import AuditLog

from audit_case_worker import ORCHESTRATOR_AUDIT_SOURCE
from models.cases import CaseORM
from models.decision import DecisionORM
from models.outbox import OUTBOX_EVENT_LABEL_PROPAGATE, OutboxDAO
from utils.entity_parser import ParsedEntities, parse_entities

logger = logging.getLogger(__name__)

LABEL_PROPAGATE_SCHEMA = "tarka.label_propagate.v1"


class LabelPropagationError(ValueError):
    """Raised when label propagation inputs or context resolution fail."""


@dataclass(frozen=True, slots=True)
class EvidenceManifestSnapshot:
    """Normalized view of the original rule-engine ``EvidenceManifest`` trace."""

    manifest_id: str | None
    trace_steps: tuple[dict[str, Any], ...]


def _normalize_tag(token: str) -> str:
    cleaned = (token or "").strip()
    if not cleaned:
        raise LabelPropagationError("structural tag must be non-empty")
    if len(cleaned) > 128:
        return cleaned[:128]
    return cleaned


def evidence_manifest_from_rule_data(rule_data: dict[str, Any] | None) -> EvidenceManifestSnapshot:
    if not isinstance(rule_data, dict):
        return EvidenceManifestSnapshot(manifest_id=None, trace_steps=())

    manifest_id_raw = rule_data.get("manifest_id") or rule_data.get("transaction_id")
    manifest_id = str(manifest_id_raw).strip() if manifest_id_raw is not None else None
    if manifest_id == "":
        manifest_id = None

    trace_raw = rule_data.get("evaluation_trace")
    if not isinstance(trace_raw, list):
        trace_raw = rule_data.get("trace")
    steps: list[dict[str, Any]] = []
    if isinstance(trace_raw, list):
        for row in trace_raw:
            if isinstance(row, dict):
                steps.append(dict(row))
    return EvidenceManifestSnapshot(
        manifest_id=manifest_id,
        trace_steps=tuple(steps),
    )


async def load_evidence_manifest_snapshot(
    session: AsyncSession,
    *,
    entity_id: str,
) -> EvidenceManifestSnapshot:
    token = (entity_id or "").strip()
    if not token:
        raise LabelPropagationError("entity_id is required to load EvidenceManifest trace")

    decision = await session.scalar(
        select(DecisionORM)
        .where(DecisionORM.entity_id == token)
        .order_by(DecisionORM.created_at.desc(), DecisionORM.id.desc())
        .limit(1),
    )
    if decision is None:
        return EvidenceManifestSnapshot(manifest_id=None, trace_steps=())

    snapshot = evidence_manifest_from_rule_data(decision.raw_rule_engine_json)
    if snapshot.trace_steps:
        return snapshot

    trace_raw = decision.execution_trace_json
    steps: list[dict[str, Any]] = []
    if isinstance(trace_raw, list):
        for row in trace_raw:
            if isinstance(row, dict):
                steps.append(dict(row))
    manifest_id = snapshot.manifest_id or token
    return EvidenceManifestSnapshot(manifest_id=manifest_id, trace_steps=tuple(steps))


def structural_tags_from_evidence_and_disposition(
    *,
    ground_truth_class: str,
    disposition_text: str,
    evidence: EvidenceManifestSnapshot,
    parsed: ParsedEntities,
    shadow_reasoning: list[str] | None = None,
) -> list[str]:
    """Build retroactive structural tags from manifest trace + analyst/chargeback text."""
    tags: list[str] = []
    seen: set[str] = set()

    def _push(prefix: str, raw: str) -> None:
        token = _normalize_tag(f"{prefix}:{raw}")
        if token not in seen:
            seen.add(token)
            tags.append(token)

    _push("ground_truth", ground_truth_class.strip().upper())
    if evidence.manifest_id:
        _push("manifest", evidence.manifest_id)

    for step in evidence.trace_steps:
        rule_id = step.get("rule_id")
        if rule_id is not None and str(rule_id).strip():
            matched = step.get("matched")
            if matched is True:
                _push("matched_rule", str(rule_id).strip())
            else:
                _push("trace_rule", str(rule_id).strip())

    for order_id in parsed.order_ids:
        _push("order_id", order_id)
    for email in parsed.emails:
        _push("email", email)
    for tracking in parsed.tracking_numbers:
        _push("tracking", tracking)

    if shadow_reasoning:
        for reason in shadow_reasoning:
            token = str(reason or "").strip()
            if token:
                _push("shadow_reason", token)

    disposition = disposition_text.strip()
    if disposition:
        _push("disposition", disposition[:96])

    return tags


async def resolve_disposition_text(
    session: AsyncSession,
    *,
    payload: dict[str, Any],
) -> str:
    parts: list[str] = []

    direct = payload.get("disposition_text")
    if isinstance(direct, str) and direct.strip():
        parts.append(direct.strip())

    metadata = payload.get("operational_metadata")
    if isinstance(metadata, dict):
        for key in (
            "chargeback_reason_code",
            "refund_reason_code",
            "reason_code",
            "analyst_notes",
        ):
            raw = metadata.get(key)
            if isinstance(raw, str) and raw.strip():
                parts.append(raw.strip())

    audit_log_id = payload.get("audit_log_id")
    if audit_log_id is not None:
        try:
            log_id = int(audit_log_id)
        except (TypeError, ValueError) as exc:
            raise LabelPropagationError(f"invalid audit_log_id: {audit_log_id!r}") from exc
        if log_id >= 1:
            log = await session.get(AuditLog, log_id)
            if log is not None:
                if isinstance(log.agent_notes, str) and log.agent_notes.strip():
                    parts.append(log.agent_notes.strip())
                try:
                    body = json.loads(log.action_taken or "{}")
                except json.JSONDecodeError:
                    body = {}
                if isinstance(body, dict):
                    for key in ("justification", "reason_code", "new_status"):
                        raw = body.get(key)
                        if isinstance(raw, str) and raw.strip():
                            parts.append(raw.strip())

    deduped: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if part not in seen:
            seen.add(part)
            deduped.append(part)
    return "\n".join(deduped)


async def load_transaction_for_entity(
    session: AsyncSession,
    *,
    entity_id: str,
) -> TransactionSchema:
    token = (entity_id or "").strip()
    if not token:
        raise LabelPropagationError("entity_id is required to rebuild transaction envelope")

    case = await session.scalar(
        select(CaseORM)
        .where(CaseORM.entity_id == token)
        .order_by(CaseORM.opened_at.desc())
        .limit(1),
    )
    if case is None:
        raise LabelPropagationError(f"no lifecycle case for entity_id={token!r}")

    log = await session.get(AuditLog, int(case.transaction_id))
    if log is None:
        raise LabelPropagationError(
            f"audit_logs.id={case.transaction_id} missing for entity_id={token!r}",
        )

    try:
        body = json.loads(log.action_taken or "{}")
    except json.JSONDecodeError as exc:
        raise LabelPropagationError("ingest audit action_taken is not valid JSON") from exc

    if not isinstance(body, dict):
        raise LabelPropagationError("ingest audit action_taken must be a JSON object")

    if body.get("source") != ORCHESTRATOR_AUDIT_SOURCE:
        logger.warning(
            "label_propagation_unexpected_audit_source entity_id=%s source=%s",
            token,
            body.get("source"),
        )

    envelope = body.get("transaction_envelope")
    if isinstance(envelope, dict):
        try:
            return TransactionSchema.model_validate(envelope)
        except ValidationError as exc:
            raise LabelPropagationError("transaction_envelope failed validation") from exc

    raise LabelPropagationError(
        f"transaction_envelope missing on audit_logs.id={case.transaction_id} for entity_id={token!r}",
    )


def build_label_propagate_payload(
    *,
    normalized_label_id: UUID,
    entity_id: str,
    source_type: str,
    source_id: UUID,
    ground_truth_class: str,
    disposition_text: str,
    case_history_id: int | None = None,
    audit_log_id: int | None = None,
    operational_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": LABEL_PROPAGATE_SCHEMA,
        "normalized_label_id": str(normalized_label_id),
        "entity_id": entity_id,
        "source_type": source_type,
        "source_id": str(source_id),
        "ground_truth_class": ground_truth_class,
        "disposition_text": disposition_text,
    }
    if case_history_id is not None:
        payload["case_history_id"] = int(case_history_id)
    if audit_log_id is not None:
        payload["audit_log_id"] = int(audit_log_id)
    if operational_metadata is not None:
        payload["operational_metadata"] = operational_metadata
    return payload


async def enqueue_label_propagate_task(
    session: AsyncSession,
    *,
    normalized_label_id: UUID,
    entity_id: str,
    source_type: str,
    source_id: UUID,
    ground_truth_class: str,
    disposition_text: str,
    case_history_id: int | None = None,
    audit_log_id: int | None = None,
    operational_metadata: dict[str, Any] | None = None,
) -> None:
    """Insert a ``LABEL_PROPAGATE`` outbox row in the caller's open transaction."""
    idempotency_key = f"label_propagate:{normalized_label_id}"
    payload = build_label_propagate_payload(
        normalized_label_id=normalized_label_id,
        entity_id=entity_id,
        source_type=source_type,
        source_id=source_id,
        ground_truth_class=ground_truth_class,
        disposition_text=disposition_text,
        case_history_id=case_history_id,
        audit_log_id=audit_log_id,
        operational_metadata=operational_metadata,
    )
    await OutboxDAO.create_task(
        session,
        OUTBOX_EVENT_LABEL_PROPAGATE,
        idempotency_key,
        payload,
    )


def validate_label_propagate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema") != LABEL_PROPAGATE_SCHEMA:
        raise LabelPropagationError(
            f"label propagate payload schema must be {LABEL_PROPAGATE_SCHEMA!r}",
        )
    label_raw = payload.get("normalized_label_id")
    entity_id = payload.get("entity_id")
    ground_truth = payload.get("ground_truth_class")
    if not isinstance(label_raw, str) or not label_raw.strip():
        raise LabelPropagationError("normalized_label_id is required")
    if not isinstance(entity_id, str) or not entity_id.strip():
        raise LabelPropagationError("entity_id is required")
    if not isinstance(ground_truth, str) or ground_truth.strip().upper() not in {
        "FRAUD",
        "LEGITIMATE",
    }:
        raise LabelPropagationError("ground_truth_class must be FRAUD or LEGITIMATE")
    try:
        UUID(label_raw.strip())
    except ValueError as exc:
        raise LabelPropagationError("normalized_label_id must be a UUID") from exc
    return payload
