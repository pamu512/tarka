"""Outbox handler: propagate ``normalized_labels`` through ShadowAgent retroactive tagging."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from database import atomic_transaction
from label_propagation import (
    LabelPropagationError,
    load_evidence_manifest_snapshot,
    load_transaction_for_entity,
    resolve_disposition_text,
    validate_label_propagate_payload,
)
from messaging.labels_jetstream import (
    LabelsJetStreamPublishError,
    publish_normalized_label_enriched,
)
from models.label_dlq import TarkaLabelDlqDAO
from models.normalized_labels import NormalizedLabelDAO
from models.outbox import OUTBOX_EVENT_LABEL_PROPAGATE
from schemas.label_bus import (
    LabelBusValidationError,
    build_label_bus_emit_dict,
    validate_label_bus_emit_payload,
    validate_structural_tag_list,
)
from utils.entity_parser import parse_entities
from workers.handlers.base import BaseOutboxHandler, OutboxProcessorDeps

logger = logging.getLogger(__name__)

_SHADOW_EVAL_MAX_RETRIES = 3
_SHADOW_EVAL_BASE_BACKOFF_SEC = 1.0
SHADOW_EVALUATION_FAILED_PLACEHOLDER_TAG = "system:shadow_evaluation_failed"


class LabelPropagatorPayloadError(ValueError):
    """Raised when a ``LABEL_PROPAGATE`` outbox payload is missing required fields."""


class LabelPropagatorHandler(BaseOutboxHandler):
    """Run Shadow retroactive structural tagging for one ``normalized_labels`` row."""

    event_type = OUTBOX_EVENT_LABEL_PROPAGATE

    def __init__(self, deps: OutboxProcessorDeps) -> None:
        super().__init__(deps)
        self._shadow_runtime_cache: Any | None = deps.shadow_runtime

    async def execute(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            raise LabelPropagatorPayloadError("payload must be a dict")

        try:
            validated = validate_label_propagate_payload(payload)
        except LabelPropagationError as exc:
            raise LabelPropagatorPayloadError(str(exc)) from exc

        label_id = UUID(str(validated["normalized_label_id"]).strip())
        entity_id = str(validated["entity_id"]).strip()
        ground_truth_class = str(validated["ground_truth_class"]).strip().upper()

        async with self._deps.session_factory() as session:
            disposition_text = await resolve_disposition_text(session, payload=validated)
            evidence = await load_evidence_manifest_snapshot(session, entity_id=entity_id)
            transaction = await load_transaction_for_entity(session, entity_id=entity_id)

        parsed = parse_entities(disposition_text)
        manifest_payload: dict[str, Any] = {
            "manifest_id": evidence.manifest_id,
            "trace_steps": list(evidence.trace_steps),
            "transaction": transaction.model_dump(mode="json"),
        }
        feedback_context: dict[str, Any] = {
            "ground_truth_class": ground_truth_class,
            "disposition_text": disposition_text,
            "source_type": validated.get("source_type"),
            "source_id": validated.get("source_id"),
            "normalized_label_id": str(label_id),
            "entity_id": entity_id,
            "parsed_entities": {
                "order_ids": list(parsed.order_ids),
                "emails": list(parsed.emails),
                "tracking_numbers": list(parsed.tracking_numbers),
            },
        }
        operational_metadata = validated.get("operational_metadata")
        if isinstance(operational_metadata, dict):
            feedback_context["operational_metadata"] = operational_metadata

        structural_tags = await self._run_retroactive_label_evaluate(
            manifest_payload=manifest_payload,
            feedback_context=feedback_context,
            entity_id=entity_id,
        )

        try:
            validate_structural_tag_list(structural_tags)
        except LabelBusValidationError as exc:
            await self._route_malformed_label_to_dlq(
                normalized_label_id=label_id,
                entity_id=entity_id,
                ground_truth_class=ground_truth_class,
                candidate_payload={
                    "stage": "retroactive_structural_tags",
                    "structural_tags": list(structural_tags),
                    "normalized_label_id": str(label_id),
                    "entity_id": entity_id,
                    "ground_truth_class": ground_truth_class,
                },
                rejection_reason=str(exc),
            )
            logger.warning(
                "label_propagator_dlq_retroactive_tags normalized_label_id=%s entity_id=%s",
                label_id,
                entity_id,
            )
            return

        enriched_row = None
        async with atomic_transaction(self._deps.session_factory) as session:
            await NormalizedLabelDAO.append_structural_tags(session, label_id, structural_tags)
            enriched_row = await NormalizedLabelDAO.mark_propagated(session, label_id)

        emit_dict = build_label_bus_emit_dict(enriched_row)
        try:
            validated_emit = validate_label_bus_emit_payload(emit_dict)
        except LabelBusValidationError as exc:
            await self._route_malformed_label_to_dlq(
                normalized_label_id=label_id,
                entity_id=entity_id,
                ground_truth_class=ground_truth_class,
                candidate_payload=emit_dict,
                rejection_reason=str(exc),
            )
            logger.warning(
                "label_propagator_dlq_bus_payload normalized_label_id=%s entity_id=%s",
                label_id,
                entity_id,
            )
            return

        jetstream = getattr(self._deps, "nats_jetstream", None)
        if jetstream is None:
            raise LabelsJetStreamPublishError(
                "NATS JetStream is required to publish enriched normalized label events "
                "(set NATS_URL and run JetStream bootstrap)",
            )

        await publish_normalized_label_enriched(
            jetstream,
            label_entity=validated_emit.model_dump(mode="json", by_alias=True),
        )

        logger.info(
            "label_propagator_completed normalized_label_id=%s entity_id=%s tag_count=%s",
            label_id,
            entity_id,
            len(structural_tags),
        )

    async def _run_retroactive_label_evaluate(
        self,
        *,
        manifest_payload: dict[str, Any],
        feedback_context: dict[str, Any],
        entity_id: str,
    ) -> list[str]:
        from shadow_agent.retroactive_label import evaluate_retroactive_label  # noqa: PLC0415

        runtime = await self._resolve_shadow_runtime()
        entity_s = str(entity_id)

        async def _evaluate() -> list[str]:
            return await evaluate_retroactive_label(
                manifest_payload,
                feedback_context,
                llm_client=runtime.llm_client,
            )

        last_error: BaseException | None = None
        for attempt in range(_SHADOW_EVAL_MAX_RETRIES + 1):
            try:
                tags = await runtime.gateway.run_shadow_investigate_inference(_evaluate)
            except Exception as exc:
                last_error = exc
                if not _is_shadow_eval_retryable(exc) or attempt >= _SHADOW_EVAL_MAX_RETRIES:
                    break
                delay = _shadow_eval_backoff_seconds(attempt)
                logger.warning(
                    "label_propagator_shadow_eval_retry entity_id=%s attempt=%s delay_sec=%s exc_type=%s",
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
                delay = _shadow_eval_backoff_seconds(attempt)
                logger.warning(
                    "label_propagator_shadow_eval_empty_tags entity_id=%s attempt=%s delay_sec=%s",
                    entity_s,
                    attempt + 1,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            try:
                validate_structural_tag_list(tags)
            except LabelBusValidationError as exc:
                last_error = exc
                if attempt >= _SHADOW_EVAL_MAX_RETRIES:
                    break
                delay = _shadow_eval_backoff_seconds(attempt)
                logger.warning(
                    "label_propagator_shadow_eval_garbled_tags entity_id=%s attempt=%s delay_sec=%s",
                    entity_s,
                    attempt + 1,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            logger.info(
                "label_propagator_retroactive_label_ok entity_id=%s tag_count=%s attempt=%s",
                entity_s,
                len(tags),
                attempt + 1,
            )
            return tags

        logger.error(
            "label_propagator_shadow_eval_exhausted entity_id=%s retries=%s placeholder_tag=%s last_error=%s",
            entity_s,
            _SHADOW_EVAL_MAX_RETRIES,
            SHADOW_EVALUATION_FAILED_PLACEHOLDER_TAG,
            last_error,
        )
        return [SHADOW_EVALUATION_FAILED_PLACEHOLDER_TAG]

    async def _route_malformed_label_to_dlq(
        self,
        *,
        normalized_label_id: UUID,
        entity_id: str,
        ground_truth_class: str,
        candidate_payload: dict[str, Any],
        rejection_reason: str,
    ) -> None:
        async with atomic_transaction(self._deps.session_factory) as session:
            await TarkaLabelDlqDAO.record_malformed_label(
                session,
                normalized_label_id=normalized_label_id,
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
                "label propagator requires shadow_agent package (pip install / PYTHONPATH)",
            ) from exc
        runtime = await bootstrap_shadow_investigate_runtime()
        self._shadow_runtime_cache = runtime
        return runtime


def _shadow_eval_backoff_seconds(attempt: int) -> float:
    """Exponential backoff: 1s, 2s, 4s, … for attempt index 0, 1, 2, …"""
    if attempt < 0:
        return _SHADOW_EVAL_BASE_BACKOFF_SEC
    return _SHADOW_EVAL_BASE_BACKOFF_SEC * (2**attempt)


def _is_shadow_eval_retryable(exc: BaseException) -> bool:
    """True for Ollama/sidecar timeouts, transport failures, and garbled LLM output."""
    import httpx  # noqa: PLC0415
    from shadow_agent.llm_client import ShadowLLMError  # noqa: PLC0415

    if isinstance(
        exc,
        (
            ShadowLLMError,
            LabelBusValidationError,
            TimeoutError,
            asyncio.TimeoutError,
            ConnectionError,
            OSError,
            ValueError,
            RuntimeError,
        ),
    ):
        return True
    if isinstance(exc, httpx.HTTPError):
        return True
    return False
