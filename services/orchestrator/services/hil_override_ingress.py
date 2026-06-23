"""Atomic HIL override ingress: ClickHouse row + operational signal audit."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from analytics.hil_context_store import (
    HilContextOverrideStore,
    HilContextStoreError,
    HilOverrideType,
)
from schemas.hil_overrides import HilOverrideCreate
from schemas.operational_signals import (
    HilContextOverrideMetadata,
    OperationalSignalCreate,
    SignalType,
)
from services.operational_signal_persist import (
    persist_operational_signal_with_shadow_retro_tag,
)


def _default_expiry() -> datetime:
    return datetime.now(tz=UTC) + timedelta(days=90)


def _normalize_expiry(raw: datetime | None) -> datetime:
    if raw is None:
        return _default_expiry()
    if raw.tzinfo is None:
        return raw.replace(tzinfo=UTC)
    return raw.astimezone(UTC)


def operational_signal_body_for_hil_override(
    *,
    entity_id: UUID,
    body: HilOverrideCreate,
    override_row: dict[str, object],
) -> OperationalSignalCreate:
    expires_at = str(override_row.get("expires_at") or "")
    return OperationalSignalCreate.model_validate(
        {
            "idempotency_key": body.idempotency_key,
            "target_entity_id": entity_id,
            "signal_type": SignalType.HIL_CONTEXT_OVERRIDE,
            "metadata": HilContextOverrideMetadata(
                override_type=str(override_row.get("override_type") or body.override_type.value),
                scope_key=str(override_row.get("scope_key") or body.scope_key),
                expires_at=expires_at,
                analyst_id=body.analyst_id,
                analyst_rationale=str(
                    override_row.get("analyst_rationale") or body.analyst_rationale,
                ),
            ),
        },
    )


async def apply_hil_override_with_audit(
    *,
    store: HilContextOverrideStore,
    session_factory: async_sessionmaker[AsyncSession],
    entity_id: UUID,
    body: HilOverrideCreate,
) -> tuple[UUID, dict[str, object]]:
    """
    Insert ClickHouse override row, then persist ``operational_signals`` + outbox in one transaction.

    Returns ``(event_id, override_row)``.
    """
    tenant = body.tenant_id.strip()
    entity_key = str(entity_id)
    expiry = _normalize_expiry(body.expires_at)
    otype = (
        body.override_type
        if isinstance(body.override_type, HilOverrideType)
        else HilOverrideType(str(body.override_type).strip())
    )

    try:
        store.insert_override(
            tenant_id=tenant,
            entity_id=entity_key,
            override_type=otype,
            scope_key=body.scope_key,
            expires_at=expiry,
            analyst_rationale=body.analyst_rationale,
        )
    except HilContextStoreError:
        raise

    override_row: dict[str, object] = {
        "tenant_id": tenant,
        "entity_id": entity_key,
        "override_type": otype.value,
        "scope_key": body.scope_key.strip(),
        "expires_at": expiry.isoformat(),
        "analyst_rationale": body.analyst_rationale.strip(),
    }

    signal_body = operational_signal_body_for_hil_override(
        entity_id=entity_id,
        body=body,
        override_row=override_row,
    )

    from database import atomic_transaction

    async with atomic_transaction(session_factory) as session:
        row = await persist_operational_signal_with_shadow_retro_tag(session, signal_body)
        event_id = row.id

    return event_id, override_row
