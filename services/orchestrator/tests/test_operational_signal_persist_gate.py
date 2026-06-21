"""Gate: operational signal + SHADOW_RETRO_TAG outbox atomic persist."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_persist_operational_signal_with_shadow_retro_tag() -> None:
    import models.operational_signals  # noqa: F401, PLC0415
    import models.outbox  # noqa: F401, PLC0415
    import tarka_shared.audit_trail  # noqa: F401, PLC0415

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool
    from tarka_shared.database.session import Base

    from database import atomic_transaction
    from models.operational_signals import OperationalSignalORM
    from models.outbox import OUTBOX_EVENT_SHADOW_RETRO_TAG, OutboxORM
    from schemas.operational_signals import OperationalSignalCreate, SignalType
    from services.operational_signal_persist import (
        persist_operational_signal_with_shadow_retro_tag,
    )

    entity_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

    async def _run() -> None:
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        body = OperationalSignalCreate.model_validate(
            {
                "idempotency_key": "cb:persist:4853",
                "target_entity_id": entity_id,
                "signal_type": SignalType.CHARGEBACK_RECEIVED,
                "metadata": {
                    "amount_cents": 1250,
                    "currency": "USD",
                    "chargeback_reason_code": "4853",
                    "card_network": "VISA",
                },
            },
        )

        async with atomic_transaction(fac) as session:
            row = await persist_operational_signal_with_shadow_retro_tag(session, body)
            signal_id = row.id

        async with fac() as session:
            signal_row = await session.get(OperationalSignalORM, signal_id)
            assert signal_row is not None
            assert signal_row.idempotency_key == "cb:persist:4853"
            assert signal_row.target_entity_id == entity_id

            outbox_row = await session.scalar(
                select(OutboxORM).where(OutboxORM.event_type == OUTBOX_EVENT_SHADOW_RETRO_TAG),
            )
            assert outbox_row is not None
            assert outbox_row.idempotency_key == "shadow_tag_ops:cb:persist:4853"
            assert outbox_row.payload["entity_id"] == entity_id
            assert outbox_row.payload["signal_id"] == str(signal_id)
            assert outbox_row.payload["metadata"]["chargeback_reason_code"] == "4853"

        await engine.dispose()

    asyncio.run(_run())
