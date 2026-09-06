"""Field registry overlay + map store (sqlite+aiosqlite)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from decision_api.db import Base
from decision_api.field_store import (
    FieldRegistrySeedLocked,
    FieldRegistryUnknownName,
    list_maps,
    list_overlay,
    upsert_map,
    upsert_overlay,
)


@pytest.fixture
async def session():
    pytest.importorskip("aiosqlite")
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as sess:
        yield sess
    await engine.dispose()


@pytest.mark.asyncio
async def test_upsert_overlay_lists_order_channel(session):
    row = await upsert_overlay(
        session, "acme", "order_channel", "who sold", "new_feature"
    )
    assert row.name == "order_channel"
    names = [r.name for r in await list_overlay(session, "acme")]
    assert "order_channel" in names


@pytest.mark.asyncio
async def test_upsert_overlay_seed_name_locked(session):
    with pytest.raises(FieldRegistrySeedLocked):
        await upsert_overlay(session, "acme", "event_count_1h", "nope", "new_feature")


@pytest.mark.asyncio
async def test_upsert_overlay_tx_prefix_rejected(session):
    with pytest.raises(ValueError):
        await upsert_overlay(session, "acme", "tx_count_1h", "legacy", "new_feature")


@pytest.mark.asyncio
async def test_upsert_overlay_rejects_tarka_core_source(session):
    with pytest.raises(ValueError, match="tarka_core"):
        await upsert_overlay(session, "acme", "order_channel", "who sold", "tarka_core")


@pytest.mark.asyncio
async def test_upsert_map_txn_amt_to_amount(session):
    row = await upsert_map(session, "acme", "txn_amt", "amount")
    assert row.buyer_key == "txn_amt"
    assert row.registry_name == "amount"
    keys = [(m.buyer_key, m.registry_name) for m in await list_maps(session, "acme")]
    assert ("txn_amt", "amount") in keys


@pytest.mark.asyncio
async def test_upsert_map_unknown_registry_name(session):
    with pytest.raises(FieldRegistryUnknownName):
        await upsert_map(session, "acme", "x", "not_a_field")
