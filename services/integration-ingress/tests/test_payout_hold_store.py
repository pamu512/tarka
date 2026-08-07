"""Durable marketplace payout hold store (Marketplace P0 Task 2)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from integration_ingress.db import Base
from integration_ingress.payout_hold_store import list_holds, release_hold, upsert_hold
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session(tmp_path) -> AsyncIterator[AsyncSession]:
    from integration_ingress import models as _models  # noqa: F401

    db_path = tmp_path / "payout_hold_store_test.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
    await eng.dispose()


@pytest.mark.asyncio
async def test_upsert_list_release_roundtrip(session: AsyncSession) -> None:
    row = await upsert_hold(
        session,
        tenant_id="t1",
        payout_id="po_1",
        entity_id="seller_1",
        status="held",
        hold_reason="tag:action:payout_hold",
        held_by="evaluate",
        decision_id="dec_1",
        trace_id="tr_1",
        tags=["action:payout_hold", "vertical:marketplace"],
        amount=120.5,
        currency="USD",
        hold_duration_hours=72,
    )
    assert row["status"] == "held"
    listed = await list_holds(session, "t1", limit=10)
    assert any(p["payout_id"] == "po_1" for p in listed)
    released = await release_hold(session, "t1", "po_1", released_by="analyst")
    assert released is not None
    assert released["status"] == "released"
