"""Postgres ↔ Redis entity signature sync helpers."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from decision_api.db import Base
from decision_api.models import EntitySignatureState
from decision_api.redis_signature_sync import (
    canonical_tags_blob,
    reconcile_batch,
    upsert_entity_signature_state,
)
from decision_api.redis_store import RedisTags
from tarka_core.cache import LocalDictCache


def test_canonical_tags_blob_sorted_unique() -> None:
    blob = canonical_tags_blob(["z", "a", "a", "b"])
    assert json.loads(blob) == ["a", "b", "z"]


@pytest.mark.asyncio
async def test_reconcile_batch_repopulates_when_missing() -> None:
    kv = LocalDictCache()
    store = RedisTags("")
    await store.connect(kv_fallback=kv)

    class Row:
        tenant_id = "t1"
        entity_id = "e1"
        tags_json = ["alpha", "beta"]

    m, d = await reconcile_batch(store, [Row()])
    assert m == 1 and d == 0

    raw = await store.get_tags("t1", "e1")
    assert sorted(raw) == ["alpha", "beta"]


@pytest.mark.asyncio
async def test_upsert_entity_signature_state_roundtrip() -> None:
    pytest.importorskip("aiosqlite")

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        await upsert_entity_signature_state(session, "acme", "u1", ["x", "y"])
        await session.commit()

    async with Session() as session:
        row = (
            await session.execute(
                select(EntitySignatureState).where(
                    EntitySignatureState.tenant_id == "acme",
                    EntitySignatureState.entity_id == "u1",
                )
            )
        ).scalar_one()
        assert sorted(row.tags_json) == ["x", "y"]

    await engine.dispose()
