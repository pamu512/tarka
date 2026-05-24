"""Atomic persistence for operational signals + ``SHADOW_RETRO_TAG`` outbox enqueue."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.models.operational_signals import OperationalSignalDAO, OperationalSignalORM
from orchestrator.models.outbox import OUTBOX_EVENT_SHADOW_RETRO_TAG, OutboxDAO
from orchestrator.schemas.operational_signals import OperationalSignalCreate


def shadow_retro_outbox_payload(
    body: OperationalSignalCreate,
    *,
    signal_id: UUID,
) -> dict[str, Any]:
    return {
        "entity_id": str(body.entity_id),
        "signal_id": str(signal_id),
        "metadata": body.metadata_json(),
    }


async def persist_operational_signal_with_shadow_retro_tag(
    session: AsyncSession,
    body: OperationalSignalCreate,
) -> OperationalSignalORM:
    """
    Insert ``operational_signals`` and ``tarka_outbox`` (``SHADOW_RETRO_TAG``) in the caller transaction.
    """
    row = await OperationalSignalDAO.create(
        session,
        idempotency_key=body.idempotency_key,
        target_entity_id=body.target_entity_id,
        signal_type=body.signal_type,
        metadata=body.metadata_json(),
    )
    await OutboxDAO.create_task(
        session,
        event_type=OUTBOX_EVENT_SHADOW_RETRO_TAG,
        idempotency_key=f"shadow_tag_ops:{body.idempotency_key}",
        payload=shadow_retro_outbox_payload(body, signal_id=row.id),
    )
    return row
