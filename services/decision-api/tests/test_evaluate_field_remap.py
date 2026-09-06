"""Evaluate remap hook: source order + load_maps_or_empty (no full pipeline)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from decision_api.db import Base
from decision_api.field_store import upsert_map
from field_registry import apply_field_maps


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


def test_pipeline_source_remaps_after_replay():
    text = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "decision_api"
        / "evaluate"
        / "pipeline.py"
    ).read_text(encoding="utf-8")
    assert "apply_field_maps" in text
    assert text.index("check_and_store_replay_signature") < text.index("apply_field_maps")


@pytest.mark.asyncio
async def test_load_maps_or_empty_swallows_and_apply(session):
    from decision_api.field_store import load_maps_or_empty

    await upsert_map(session, "t1", "txn_amt", "amount")
    maps = await load_maps_or_empty(session, "t1")
    out = apply_field_maps({"txn_amt": 9}, maps)
    assert out["amount"] == 9

    empty = await load_maps_or_empty(object(), "t1")
    assert empty == []
