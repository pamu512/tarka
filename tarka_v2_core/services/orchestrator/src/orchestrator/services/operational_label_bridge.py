"""Bridge operational signal ingress into ``normalized_labels`` + label propagation outbox."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.label_propagation import enqueue_label_propagate_task
from orchestrator.models.normalized_labels import (
    SOURCE_TYPE_CHARGEBACK,
    GroundTruthClass,
    NormalizedLabelDAO,
    NormalizedLabelORM,
)
from orchestrator.models.operational_signals import OperationalSignalORM
from orchestrator.schemas.operational_signals import (
    ChargebackReceivedMetadata,
    ChargebackReversedMetadata,
    ManualOverrideAction,
    ManualOverrideMetadata,
    OperationalSignalCreate,
    RefundIssuedMetadata,
    SignalType,
)

logger = logging.getLogger(__name__)


def source_type_for_operational_signal(signal_type: SignalType) -> str:
    if signal_type in (SignalType.CHARGEBACK_RECEIVED, SignalType.CHARGEBACK_REVERSED):
        return SOURCE_TYPE_CHARGEBACK
    return signal_type.value


def ground_truth_class_for_operational_signal(
    body: OperationalSignalCreate,
) -> GroundTruthClass | None:
    """Map operational signal types to consortium ground-truth classes."""
    if body.signal_type == SignalType.CHARGEBACK_RECEIVED:
        return GroundTruthClass.FRAUD
    if body.signal_type == SignalType.CHARGEBACK_REVERSED:
        return GroundTruthClass.LEGITIMATE
    if body.signal_type == SignalType.REFUND_ISSUED:
        return GroundTruthClass.LEGITIMATE
    if body.signal_type == SignalType.MANUAL_OVERRIDE:
        meta = body.metadata
        if not isinstance(meta, ManualOverrideMetadata):
            return None
        if meta.override_action in (ManualOverrideAction.BLOCK, ManualOverrideAction.FLAG):
            return GroundTruthClass.FRAUD
        if meta.override_action == ManualOverrideAction.ALLOW:
            return GroundTruthClass.LEGITIMATE
        return None
    return None


def disposition_text_for_operational_signal(body: OperationalSignalCreate) -> str:
    meta = body.metadata
    if isinstance(meta, ChargebackReceivedMetadata):
        return (
            f"Chargeback received reason {meta.chargeback_reason_code} "
            f"network {meta.card_network.value} amount {meta.amount_cents} {meta.currency}"
        )
    if isinstance(meta, ChargebackReversedMetadata):
        return (
            f"Chargeback reversed reason {meta.reversal_reason_code} "
            f"original {meta.chargeback_reason_code}"
        )
    if isinstance(meta, RefundIssuedMetadata):
        return (
            f"Refund issued reason {meta.refund_reason_code} "
            f"channel {meta.refund_channel.value}"
        )
    if isinstance(meta, ManualOverrideMetadata):
        parts = [f"Manual override {meta.override_action.value} reason {meta.reason_code}"]
        if meta.notes and meta.notes.strip():
            parts.append(meta.notes.strip())
        return " ".join(parts)
    return body.signal_type.value


def initial_tags_for_operational_signal(body: OperationalSignalCreate) -> list[str]:
    tags: list[str] = ["operational_signal", f"signal_type:{body.signal_type.value.lower()}"]
    meta_json = body.metadata_json()
    for key in ("chargeback_reason_code", "refund_reason_code", "reason_code"):
        raw = meta_json.get(key)
        if isinstance(raw, str) and raw.strip():
            tags.append(f"reason:{raw.strip().lower()}")
            break
    card_network = meta_json.get("card_network")
    if isinstance(card_network, str) and card_network.strip():
        tags.append(f"card_network:{card_network.strip().lower()}")
    override_action = meta_json.get("override_action")
    if isinstance(override_action, str) and override_action.strip():
        tags.append(f"override_action:{override_action.strip().lower()}")
    return tags


async def _fetch_existing_operational_label(
    session: AsyncSession,
    *,
    source_type: str,
    source_id: Any,
) -> NormalizedLabelORM | None:
    return await session.scalar(
        select(NormalizedLabelORM)
        .where(
            NormalizedLabelORM.source_type == source_type,
            NormalizedLabelORM.source_id == source_id,
        )
        .limit(1),
    )


async def enqueue_operational_signal_label_propagation(
    session: AsyncSession,
    *,
    signal: OperationalSignalORM,
    body: OperationalSignalCreate,
) -> NormalizedLabelORM | None:
    """
    Create ``normalized_labels`` + ``LABEL_PROPAGATE`` outbox row for one operational signal.

    Idempotent per ``(source_type, source_id)`` within the caller's transaction.
    """
    ground_truth = ground_truth_class_for_operational_signal(body)
    if ground_truth is None:
        logger.info(
            "operational_label_bridge_skip signal_id=%s signal_type=%s",
            signal.id,
            body.signal_type.value,
        )
        return None

    source_type = source_type_for_operational_signal(body.signal_type)
    existing = await _fetch_existing_operational_label(
        session,
        source_type=source_type,
        source_id=signal.id,
    )
    if existing is not None:
        return existing

    label_row = await NormalizedLabelDAO.create_operational_signal_label(
        session,
        operational_signal_id=signal.id,
        source_type=source_type,
        entity_id=str(body.target_entity_id),
        ground_truth_class=ground_truth,
        tags=initial_tags_for_operational_signal(body),
    )
    disposition_text = disposition_text_for_operational_signal(body)
    await enqueue_label_propagate_task(
        session,
        normalized_label_id=label_row.id,
        entity_id=label_row.entity_id,
        source_type=label_row.source_type,
        source_id=label_row.source_id,
        ground_truth_class=label_row.ground_truth_class,
        disposition_text=disposition_text,
        operational_metadata=body.metadata_json(),
    )
    logger.info(
        "operational_label_bridge_enqueued signal_id=%s normalized_label_id=%s entity_id=%s",
        signal.id,
        label_row.id,
        label_row.entity_id,
    )
    return label_row
