"""Outbox handler: ``SHADOW_RETRO_TAG`` → ClickHouse manifest + Shadow retroactive tags → ``normalized_labels``."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.analytics.evidence_manifest_fetch import fetch_most_recent_evidence_manifest
from orchestrator.database import atomic_transaction
from orchestrator.label_propagation import (
    LabelPropagationError,
    load_evidence_manifest_snapshot,
    load_transaction_for_entity,
)
from orchestrator.messaging.labels_jetstream import (
    LabelsJetStreamPublishError,
    publish_normalized_label_enriched,
)
from orchestrator.models.cases import CaseHistoryORM, CaseStatus
from orchestrator.models.label_dlq import TarkaLabelDlqDAO
from orchestrator.models.normalized_labels import (
    SOURCE_TYPE_ANALYST_DISPOSITION,
    GroundTruthClass,
    NormalizedLabelDAO,
    NormalizedLabelORM,
    case_history_source_id,
    ground_truth_class_for_resolved_status,
)
from orchestrator.models.operational_signals import OperationalSignalORM
from orchestrator.models.outbox import OUTBOX_EVENT_SHADOW_RETRO_TAG
from orchestrator.schemas.label_bus import (
    LabelBusValidationError,
    build_label_bus_emit_dict,
    validate_label_bus_emit_payload,
    validate_structural_tag_list,
)
from orchestrator.schemas.operational_signals import OperationalSignalCreate
from orchestrator.services.operational_label_bridge import (
    disposition_text_for_operational_signal,
    ground_truth_class_for_operational_signal,
    source_type_for_operational_signal,
)
from orchestrator.workers.handlers.base import BaseOutboxHandler, OutboxProcessorDeps
from orchestrator.workers.handlers.label_propagator import (
    SHADOW_EVALUATION_FAILED_PLACEHOLDER_TAG,
    _is_shadow_eval_retryable,
    _shadow_eval_backoff_seconds,
)

logger = logging.getLogger(__name__)

_SHADOW_EVAL_MAX_RETRIES = 3


class ShadowRetroTagPayloadError(ValueError):
    """Raised when a ``SHADOW_RETRO_TAG`` outbox payload is missing required fields."""


@dataclass(frozen=True, slots=True)
class ShadowRetroTagPayload:
    entity_id: str
    signal_id: UUID | None
    case_id: str | None
    new_status: str | None
    analyst_notes: str | None
    metadata: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class ShadowRetroLabelAnchor:
    source_type: str
    source_id: UUID
    ground_truth_class: GroundTruthClass
    disposition_text: str


def validate_shadow_retro_tag_payload(payload: dict[str, Any]) -> ShadowRetroTagPayload:
    if not isinstance(payload, dict):
        raise ShadowRetroTagPayloadError("payload must be a dict")

    entity_raw = payload.get("entity_id")
    if not isinstance(entity_raw, str) or not entity_raw.strip():
        raise ShadowRetroTagPayloadError("entity_id is required")
    entity_id = entity_raw.strip()

    signal_id: UUID | None = None
    signal_raw = payload.get("signal_id")
    if signal_raw is not None:
        try:
            signal_id = UUID(str(signal_raw).strip())
        except ValueError as exc:
            raise ShadowRetroTagPayloadError("signal_id must be a UUID when present") from exc

    case_id: str | None = None
    case_raw = payload.get("case_id")
    if isinstance(case_raw, str) and case_raw.strip():
        case_id = case_raw.strip()

    new_status: str | None = None
    status_raw = payload.get("new_status")
    if isinstance(status_raw, str) and status_raw.strip():
        new_status = status_raw.strip()

    analyst_notes: str | None = None
    notes_raw = payload.get("analyst_notes")
    if isinstance(notes_raw, str) and notes_raw.strip():
        analyst_notes = notes_raw.strip()

    metadata: dict[str, Any] | None = None
    metadata_raw = payload.get("metadata")
    if metadata_raw is not None:
        if not isinstance(metadata_raw, dict):
            raise ShadowRetroTagPayloadError("metadata must be a JSON object when present")
        metadata = dict(metadata_raw)

    if signal_id is None and case_id is None:
        raise ShadowRetroTagPayloadError("payload must include signal_id or case_id")

    if signal_id is not None and case_id is not None:
        raise ShadowRetroTagPayloadError("payload must not include both signal_id and case_id")

    if case_id is not None and new_status is None:
        raise ShadowRetroTagPayloadError("case_id payloads require new_status")

    return ShadowRetroTagPayload(
        entity_id=entity_id,
        signal_id=signal_id,
        case_id=case_id,
        new_status=new_status,
        analyst_notes=analyst_notes,
        metadata=metadata,
    )


def _feedback_context_from_payload(
    parsed: ShadowRetroTagPayload,
    *,
    anchor: ShadowRetroLabelAnchor,
) -> dict[str, Any]:
    feedback: dict[str, Any] = {
        "ground_truth_class": anchor.ground_truth_class.value,
        "entity_id": parsed.entity_id,
        "disposition_text": anchor.disposition_text,
        "source_type": anchor.source_type,
        "source_id": str(anchor.source_id),
    }
    if parsed.analyst_notes:
        feedback["analyst_notes"] = parsed.analyst_notes
    if parsed.metadata:
        feedback["operational_metadata"] = parsed.metadata
    if parsed.case_id:
        feedback["case_id"] = parsed.case_id
    if parsed.new_status:
        feedback["new_status"] = parsed.new_status
    return feedback


def _manifest_payload_from_clickhouse(
    *,
    clickhouse_row: dict[str, Any],
    transaction_json: dict[str, Any],
) -> dict[str, Any]:
    return {
        "manifest_id": clickhouse_row.get("manifest_id"),
        "trace_steps": list(clickhouse_row.get("trace_steps") or []),
        "signals": dict(clickhouse_row.get("signals") or {}),
        "engine_version": clickhouse_row.get("engine_version"),
        "timestamp_ns": clickhouse_row.get("timestamp_ns"),
        "final_decision": clickhouse_row.get("final_decision"),
        "total_execution_time_us": clickhouse_row.get("total_execution_time_us"),
        "transaction": transaction_json,
    }


async def _resolve_operational_anchor(
    session: AsyncSession,
    *,
    signal_id: UUID,
) -> tuple[ShadowRetroLabelAnchor, OperationalSignalORM]:
    signal = await session.get(OperationalSignalORM, signal_id)
    if signal is None:
        raise ShadowRetroTagPayloadError(f"operational signal not found: {signal_id}")

    try:
        body = OperationalSignalCreate.model_validate(
            {
                "idempotency_key": signal.idempotency_key,
                "target_entity_id": signal.target_entity_id,
                "signal_type": signal.signal_type,
                "metadata": signal.metadata_json,
            },
        )
    except Exception as exc:
        raise ShadowRetroTagPayloadError(
            f"operational signal {signal_id} failed schema validation",
        ) from exc

    ground_truth = ground_truth_class_for_operational_signal(body)
    if ground_truth is None:
        raise ShadowRetroTagPayloadError(
            f"operational signal {signal_id} has no mappable ground_truth_class",
        )

    return (
        ShadowRetroLabelAnchor(
            source_type=source_type_for_operational_signal(body.signal_type),
            source_id=signal.id,
            ground_truth_class=ground_truth,
            disposition_text=disposition_text_for_operational_signal(body),
        ),
        signal,
    )


async def _resolve_case_anchor(
    session: AsyncSession,
    *,
    case_id: str,
    new_status: str,
    analyst_notes: str | None,
) -> ShadowRetroLabelAnchor:
    try:
        resolved = CaseStatus(new_status.strip())
    except ValueError as exc:
        raise ShadowRetroTagPayloadError(f"invalid new_status: {new_status!r}") from exc

    ground_truth = ground_truth_class_for_resolved_status(resolved)
    if ground_truth is None:
        raise ShadowRetroTagPayloadError(
            f"case status {new_status!r} does not map to a ground_truth_class",
        )

    hist = await session.scalar(
        select(CaseHistoryORM)
        .where(
            CaseHistoryORM.case_id == case_id,
            CaseHistoryORM.to_status == resolved.value,
        )
        .order_by(CaseHistoryORM.id.desc())
        .limit(1),
    )
    if hist is None:
        raise ShadowRetroTagPayloadError(
            f"no case_history row for case_id={case_id!r} new_status={new_status!r}",
        )

    parts = [f"Case {case_id} resolved {resolved.value}"]
    if isinstance(hist.reason_code, str) and hist.reason_code.strip():
        parts.append(hist.reason_code.strip())
    if analyst_notes:
        parts.append(analyst_notes.strip())

    return ShadowRetroLabelAnchor(
        source_type=SOURCE_TYPE_ANALYST_DISPOSITION,
        source_id=case_history_source_id(int(hist.id)),
        ground_truth_class=ground_truth,
        disposition_text="\n".join(parts),
    )


async def _fetch_existing_label(
    session: AsyncSession,
    *,
    source_type: str,
    source_id: UUID,
) -> NormalizedLabelORM | None:
    return await session.scalar(
        select(NormalizedLabelORM)
        .where(
            NormalizedLabelORM.source_type == source_type,
            NormalizedLabelORM.source_id == source_id,
        )
        .limit(1),
    )


class ShadowRetroTagHandler(BaseOutboxHandler):
    """Evaluate retroactive Shadow tags and persist a ``normalized_labels`` row."""

    event_type = OUTBOX_EVENT_SHADOW_RETRO_TAG

    def __init__(self, deps: OutboxProcessorDeps) -> None:
        super().__init__(deps)
        self._shadow_runtime_cache: Any | None = deps.shadow_runtime

    async def execute(self, payload: dict[str, Any]) -> None:
        parsed = validate_shadow_retro_tag_payload(payload)

        async with self._deps.session_factory() as session:
            if parsed.signal_id is not None:
                anchor, _signal = await _resolve_operational_anchor(
                    session, signal_id=parsed.signal_id
                )
            else:
                assert parsed.case_id is not None and parsed.new_status is not None
                anchor = await _resolve_case_anchor(
                    session,
                    case_id=parsed.case_id,
                    new_status=parsed.new_status,
                    analyst_notes=parsed.analyst_notes,
                )

            existing = await _fetch_existing_label(
                session,
                source_type=anchor.source_type,
                source_id=anchor.source_id,
            )

        transaction_json: dict[str, Any] | None = None
        async with self._deps.session_factory() as session:
            try:
                transaction = await load_transaction_for_entity(session, entity_id=parsed.entity_id)
                transaction_json = transaction.model_dump(mode="json")
            except LabelPropagationError:
                transaction_json = None

        clickhouse_row = await fetch_most_recent_evidence_manifest(
            self._deps.clickhouse_client,
            entity_id=parsed.entity_id,
        )
        if clickhouse_row is not None:
            manifest_payload = _manifest_payload_from_clickhouse(
                clickhouse_row=clickhouse_row,
                transaction_json=transaction_json or {},
            )
        else:
            async with self._deps.session_factory() as session:
                evidence = await load_evidence_manifest_snapshot(
                    session, entity_id=parsed.entity_id
                )
            if not evidence.trace_steps and evidence.manifest_id is None:
                logger.warning(
                    "shadow_retro_tag_no_manifest entity_id=%s source_type=%s source_id=%s",
                    parsed.entity_id,
                    anchor.source_type,
                    anchor.source_id,
                )
                return
            manifest_payload = {
                "manifest_id": evidence.manifest_id,
                "trace_steps": list(evidence.trace_steps),
            }
            if transaction_json is not None:
                manifest_payload["transaction"] = transaction_json

        feedback_context = _feedback_context_from_payload(parsed, anchor=anchor)
        structural_tags = await self._evaluate_structural_tags(
            manifest_payload=manifest_payload,
            feedback_context=feedback_context,
            entity_id=parsed.entity_id,
        )

        try:
            validate_structural_tag_list(structural_tags)
        except LabelBusValidationError as exc:
            await self._route_malformed_label_to_dlq(
                entity_id=parsed.entity_id,
                ground_truth_class=anchor.ground_truth_class.value,
                candidate_payload={
                    "stage": "shadow_retro_structural_tags",
                    "structural_tags": list(structural_tags),
                    "entity_id": parsed.entity_id,
                    "source_type": anchor.source_type,
                    "source_id": str(anchor.source_id),
                },
                rejection_reason=str(exc),
            )
            logger.warning(
                "shadow_retro_tag_dlq_invalid_tags entity_id=%s source_id=%s",
                parsed.entity_id,
                anchor.source_id,
            )
            return

        enriched_row: NormalizedLabelORM | None = None
        async with atomic_transaction(self._deps.session_factory) as session:
            if existing is not None:
                label_row = await NormalizedLabelDAO.append_structural_tags(
                    session,
                    existing.id,
                    structural_tags,
                )
            elif parsed.signal_id is not None:
                label_row = await NormalizedLabelDAO.create_operational_signal_label(
                    session,
                    operational_signal_id=anchor.source_id,
                    source_type=anchor.source_type,
                    entity_id=parsed.entity_id,
                    ground_truth_class=anchor.ground_truth_class,
                    tags=structural_tags,
                )
            else:
                hist = await session.scalar(
                    select(CaseHistoryORM)
                    .where(
                        CaseHistoryORM.case_id == parsed.case_id,
                        CaseHistoryORM.to_status == parsed.new_status,
                    )
                    .order_by(CaseHistoryORM.id.desc())
                    .limit(1),
                )
                if hist is None:
                    raise ShadowRetroTagPayloadError(
                        f"case_history missing during persist for case_id={parsed.case_id!r}",
                    )
                label_row = await NormalizedLabelDAO.create_analyst_disposition(
                    session,
                    case_history_id=int(hist.id),
                    entity_id=parsed.entity_id,
                    ground_truth_class=anchor.ground_truth_class,
                    reason_code=str(hist.reason_code or parsed.new_status or ""),
                    resolved_status=str(parsed.new_status or ""),
                    tags=structural_tags,
                )
            enriched_row = await NormalizedLabelDAO.mark_propagated(session, label_row.id)

        assert enriched_row is not None
        emit_dict = build_label_bus_emit_dict(enriched_row)
        try:
            validated_emit = validate_label_bus_emit_payload(emit_dict)
        except LabelBusValidationError as exc:
            await self._route_malformed_label_to_dlq(
                entity_id=parsed.entity_id,
                ground_truth_class=anchor.ground_truth_class.value,
                candidate_payload=emit_dict,
                rejection_reason=str(exc),
            )
            logger.warning(
                "shadow_retro_tag_dlq_bus_payload entity_id=%s normalized_label_id=%s",
                parsed.entity_id,
                enriched_row.id,
            )
            return

        jetstream = getattr(self._deps, "nats_jetstream", None)
        if jetstream is None:
            raise LabelsJetStreamPublishError(
                "NATS JetStream is required to publish shadow retro normalized label events "
                "(set NATS_URL and run JetStream bootstrap)",
            )

        await publish_normalized_label_enriched(
            jetstream,
            label_entity=validated_emit.model_dump(mode="json", by_alias=True),
        )

        logger.info(
            "shadow_retro_tag_completed normalized_label_id=%s entity_id=%s source_type=%s tag_count=%s",
            enriched_row.id,
            parsed.entity_id,
            anchor.source_type,
            len(structural_tags),
        )

    async def _evaluate_structural_tags(
        self,
        *,
        manifest_payload: dict[str, Any],
        feedback_context: dict[str, Any],
        entity_id: str,
    ) -> list[str]:
        runtime = await self._resolve_shadow_runtime()
        entity_s = str(entity_id)
        evaluate_fn = getattr(runtime, "evaluate_retroactive", None)

        async def _call_evaluate() -> list[str]:
            if callable(evaluate_fn):
                tags = await evaluate_fn(manifest_payload, feedback_context)
            else:
                from shadow_agent.retroactive_label import (
                    evaluate_retroactive_label,
                )  # noqa: PLC0415

                async def _evaluate() -> list[str]:
                    return await evaluate_retroactive_label(
                        manifest_payload,
                        feedback_context,
                        llm_client=runtime.llm_client,
                    )

                tags = await runtime.gateway.run_shadow_investigate_inference(_evaluate)
            if not isinstance(tags, list):
                raise RuntimeError("evaluate_retroactive must return a list of tag strings")
            return tags

        last_error: BaseException | None = None
        for attempt in range(_SHADOW_EVAL_MAX_RETRIES + 1):
            try:
                tags = await _call_evaluate()
            except Exception as exc:
                last_error = exc
                if not _is_shadow_eval_retryable(exc) or attempt >= _SHADOW_EVAL_MAX_RETRIES:
                    break
                delay = _shadow_eval_backoff_seconds(attempt)
                logger.warning(
                    "shadow_retro_tag_eval_retry entity_id=%s attempt=%s delay_sec=%s exc_type=%s",
                    entity_s,
                    attempt + 1,
                    delay,
                    type(exc).__name__,
                )
                await asyncio.sleep(delay)
                continue

            if not isinstance(tags, list) or not tags:
                last_error = RuntimeError(
                    f"retroactive label evaluate returned no tags for entity_id={entity_s}",
                )
                if attempt >= _SHADOW_EVAL_MAX_RETRIES:
                    break
                await asyncio.sleep(_shadow_eval_backoff_seconds(attempt))
                continue

            try:
                validate_structural_tag_list(tags)
            except LabelBusValidationError as exc:
                last_error = exc
                if attempt >= _SHADOW_EVAL_MAX_RETRIES:
                    break
                await asyncio.sleep(_shadow_eval_backoff_seconds(attempt))
                continue

            return tags

        logger.error(
            "shadow_retro_tag_eval_exhausted entity_id=%s retries=%s placeholder_tag=%s last_error=%s",
            entity_s,
            _SHADOW_EVAL_MAX_RETRIES,
            SHADOW_EVALUATION_FAILED_PLACEHOLDER_TAG,
            last_error,
        )
        return [SHADOW_EVALUATION_FAILED_PLACEHOLDER_TAG]

    async def _route_malformed_label_to_dlq(
        self,
        *,
        entity_id: str,
        ground_truth_class: str,
        candidate_payload: dict[str, Any],
        rejection_reason: str,
    ) -> None:
        async with atomic_transaction(self._deps.session_factory) as session:
            await TarkaLabelDlqDAO.record_malformed_label(
                session,
                normalized_label_id=None,
                entity_id=entity_id,
                ground_truth_class=ground_truth_class,
                rejection_reason=rejection_reason,
                payload=candidate_payload,
            )

    async def _resolve_shadow_runtime(self) -> Any:
        if self._shadow_runtime_cache is not None:
            return self._shadow_runtime_cache
        try:
            from shadow_agent.workers.runtime import (
                bootstrap_shadow_investigate_runtime,
            )  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "shadow retro tag handler requires shadow_agent package (pip install / PYTHONPATH)",
            ) from exc
        runtime = await bootstrap_shadow_investigate_runtime()
        self._shadow_runtime_cache = runtime
        return runtime
