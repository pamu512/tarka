"""Unit tests for payout delay automation (Prompt 183)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from integration_ingress.db import Base
from integration_ingress.payout_delay_automation import (
    build_payout_delay_payload,
    release_payout_hold,
    update_payout_delay_config,
)
from integration_ingress.payout_hold_store import upsert_hold
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session(tmp_path) -> AsyncIterator[AsyncSession]:
    from integration_ingress import models as _models  # noqa: F401

    db_path = tmp_path / "payout_delay_unit.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
    await eng.dispose()


@pytest.mark.asyncio
async def test_high_mule_score_triggers_hold(session: AsyncSession) -> None:
    update_payout_delay_config(
        tenant_id="demo", automation_enabled=True, mule_score_hold_threshold=50
    )
    payload = await build_payout_delay_payload(session, tenant_id="demo", limit=20)
    held = [p for p in payload["payouts"] if p["status"] == "held"]
    assert held
    assert held[0]["hold_reason"] is not None
    assert held[0]["held_by"] == "payout_delay_automation"
    assert payload["source"] in ("durable", "durable+automation")


@pytest.mark.asyncio
async def test_release_clears_hold(session: AsyncSession) -> None:
    await upsert_hold(
        session,
        tenant_id="demo",
        payout_id="po_unit_rel",
        entity_id="ent_rel",
        status="held",
        hold_reason="tag:action:payout_hold",
        held_by="evaluate",
        amount=25,
        currency="USD",
    )
    await release_payout_hold(session, tenant_id="demo", payout_id="po_unit_rel")
    after = await build_payout_delay_payload(session, tenant_id="demo", limit=5)
    row = next(p for p in after["payouts"] if p["payout_id"] == "po_unit_rel")
    assert row["status"] == "released"


@pytest.mark.asyncio
async def test_automation_disabled_no_new_holds(session: AsyncSession) -> None:
    update_payout_delay_config(
        tenant_id="hold_off", automation_enabled=False, mule_score_hold_threshold=1
    )
    payload = await build_payout_delay_payload(session, tenant_id="hold_off", limit=15)
    assert payload["source"] == "durable"
    assert not any(p["held_by"] == "payout_delay_automation" for p in payload["payouts"])
