"""Unit tests for seller integrity scores (Prompt 182, Track B3 durable)."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from integration_ingress.db import Base
from integration_ingress.seller_integrity_store import upsert_seller
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_MOD_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "integration_ingress" / "seller_integrity.py"
)
_spec = importlib.util.spec_from_file_location("seller_integrity", _MOD_PATH)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["seller_integrity"] = _mod
_spec.loader.exec_module(_mod)


@pytest.fixture
async def session(tmp_path) -> AsyncIterator[AsyncSession]:
    from integration_ingress import models as _models  # noqa: F401

    db_path = tmp_path / "seller_integrity_unit.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
    await eng.dispose()


@pytest.mark.asyncio
async def test_payload_structure(session: AsyncSession) -> None:
    await upsert_seller(
        session,
        tenant_id="demo",
        seller_id="seller_a",
        successful_deliveries=100,
        review_count=30,
    )
    await upsert_seller(
        session,
        tenant_id="demo",
        seller_id="seller_b",
        successful_deliveries=50,
        review_count=40,
    )
    payload = await _mod.build_seller_integrity_payload(session, tenant_id="demo", limit=25)
    assert payload["tenant_id"] == "demo"
    assert payload["source"] == "durable"
    assert len(payload["sellers"]) == 2
    assert payload["summary"]["seller_count"] == 2
    first = payload["sellers"][0]
    assert "review_to_delivery_ratio" in first
    assert "integrity_score" in first


def test_reviews_without_deliveries_critical() -> None:
    score, tier, signals = _mod._score_seller(successful_deliveries=0, review_count=10)
    assert tier == "critical"
    assert score < 20
    assert "reviews_without_deliveries" in signals


def test_healthy_ratio_trusted() -> None:
    score, tier, _ = _mod._score_seller(successful_deliveries=200, review_count=70)
    assert tier == "trusted"
    assert score >= 85


@pytest.mark.asyncio
async def test_empty_tenant_empty_sellers(session: AsyncSession) -> None:
    payload = await _mod.build_seller_integrity_payload(session, tenant_id="nobody", limit=10)
    assert payload["source"] == "durable"
    assert payload["sellers"] == []
