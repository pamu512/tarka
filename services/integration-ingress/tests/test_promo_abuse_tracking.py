"""Unit tests for promo abuse tracking (Prompt 180, Track B3 durable)."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from integration_ingress.db import Base
from integration_ingress.promo_abuse_store import upsert_redemption
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_MOD_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "integration_ingress" / "promo_abuse_tracking.py"
)
_spec = importlib.util.spec_from_file_location("promo_abuse_tracking", _MOD_PATH)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["promo_abuse_tracking"] = _mod
_spec.loader.exec_module(_mod)


@pytest.fixture
async def session(tmp_path) -> AsyncIterator[AsyncSession]:
    from integration_ingress import models as _models  # noqa: F401

    db_path = tmp_path / "promo_abuse_unit.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
    await eng.dispose()


@pytest.mark.asyncio
async def test_empty_tenant_empty_users(session: AsyncSession) -> None:
    payload = await _mod.build_promo_abuse_payload(
        session, tenant_id="empty", coupon_code="NEWUSER50"
    )
    assert payload["source"] == "durable"
    assert payload["users"] == []
    assert payload["summary"]["unique_users"] == 0


@pytest.mark.asyncio
async def test_risk_elevated_when_over_warn(session: AsyncSession) -> None:
    for i in range(26):
        await upsert_redemption(
            session,
            tenant_id="warn_t",
            coupon_code="NEWUSER50",
            user_id=f"user_{i}",
            trace_id=f"tr_{i}",
        )
    payload = await _mod.build_promo_abuse_payload(
        session, tenant_id="warn_t", coupon_code="NEWUSER50"
    )
    assert payload["summary"]["abuse_risk"] in ("elevated", "critical")
    assert payload["summary"]["unique_users"] == 26
