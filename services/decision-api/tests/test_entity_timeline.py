"""R10: cross-entity decision timeline (evidence-cited only).

GET /v1/audit/entity-timeline merges audit rows for up to 10 entities into a
single chronological feed. Every row is a real decision_audit row (trace_id
cited); nothing is invented. No case-assignment semantics (guardrail M2):
this is a read-only workspace view.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from decision_api.models import AuditRecord, Base


@pytest.fixture
async def client():
    pytest.importorskip("aiosqlite")
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    from decision_api import main as decision_main

    async def _override_session():
        async with maker() as s:
            yield s

    decision_main.app.dependency_overrides[decision_main.get_session] = (
        _override_session
    )
    transport = ASGITransport(app=decision_main.app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c, maker
    decision_main.app.dependency_overrides.clear()
    await engine.dispose()


def _mk(maker, tenant: str, entity: str, decision: str, when: datetime) -> AuditRecord:
    return AuditRecord(
        trace_id=uuid.uuid4(),
        tenant_id=tenant,
        entity_id=entity,
        event_type="evaluate",
        decision=decision,
        score=0.5,
        tags=[],
        rule_hits=[],
        payload_snapshot={},
        created_at=when,
    )


async def test_entity_timeline_merges_and_orders(client):
    c, maker = client
    t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
    async with maker() as s:
        s.add_all(
            [
                _mk(maker, "t1", "eA", "DENY", t0),
                _mk(maker, "t1", "eB", "ALLOW", t0.replace(hour=2)),
                _mk(maker, "t1", "eA", "ALLOW", t0.replace(hour=3)),
                _mk(
                    maker, "t2", "eA", "DENY", t0.replace(hour=4)
                ),  # other tenant: excluded
            ]
        )
        await s.commit()

    r = await c.get(
        "/v1/audit/entity-timeline",
        params={
            "tenant_id": "t1",
            "entity_ids": ["eA", "eB"],
            "limit": 100,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert [e["entity_id"] for e in body["entities"]] == ["eA", "eB"]
    rows = body["timeline"]
    assert [row["entity_id"] for row in rows] == ["eA", "eB", "eA"]
    assert all(row["trace_id"] for row in rows)
    ts = [row["created_at"] for row in rows]
    assert ts == sorted(ts)
    assert rows[0]["decision"] == "DENY"


async def test_entity_timeline_caps_entities_and_rows(client):
    c, maker = client
    t0 = datetime(2026, 9, 2, tzinfo=timezone.utc)
    async with maker() as s:
        for i in range(30):
            s.add(_mk(maker, "t1", f"e{i}", "ALLOW", t0.replace(minute=i)))
        await s.commit()

    r = await c.get(
        "/v1/audit/entity-timeline",
        params={
            "tenant_id": "t1",
            "entity_ids": [f"e{i}" for i in range(30)],  # > 10 → 422
            "limit": 100,
        },
    )
    assert r.status_code == 422

    r2 = await c.get(
        "/v1/audit/entity-timeline",
        params={
            "tenant_id": "t1",
            "entity_ids": ["e0"],
            "limit": 1,
        },
    )
    assert r2.status_code == 200
    assert len(r2.json()["timeline"]) == 1
    assert r2.json()["total"] >= 1


async def test_entity_timeline_empty_is_ok(client):
    c, _ = client
    r = await c.get(
        "/v1/audit/entity-timeline",
        params={
            "tenant_id": "t1",
            "entity_ids": ["ghost"],
            "limit": 100,
        },
    )
    assert r.status_code == 200
    assert r.json()["timeline"] == []
    assert r.json()["entities"] == [{"entity_id": "ghost", "count": 0}]
