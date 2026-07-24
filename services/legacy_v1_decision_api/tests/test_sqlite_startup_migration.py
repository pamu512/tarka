from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from decision_api import db
from decision_api.models import AuditRecord


@pytest.mark.asyncio
async def test_init_db_upgrades_populated_legacy_sqlite_for_durable_idempotency(
    tmp_path,
    monkeypatch,
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.sqlite3'}")
    old_id = uuid4().hex
    old_trace = uuid4().hex
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE decision_audit (
                    id CHAR(32) PRIMARY KEY NOT NULL,
                    trace_id CHAR(32) UNIQUE NOT NULL,
                    tenant_id VARCHAR(128) NOT NULL,
                    entity_id VARCHAR(512) NOT NULL,
                    event_type VARCHAR(64) NOT NULL,
                    decision VARCHAR(32) NOT NULL,
                    score FLOAT NOT NULL,
                    tags JSON NOT NULL,
                    rule_hits JSON NOT NULL,
                    payload_snapshot JSON,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                INSERT INTO decision_audit (
                    id, trace_id, tenant_id, entity_id, event_type,
                    decision, score, tags, rule_hits, payload_snapshot
                ) VALUES (
                    :id, :trace_id, 't1', 'legacy-entity', 'payment',
                    'allow', 0.0, '[]', '[]', '{}'
                )
                """
            ),
            {"id": old_id, "trace_id": old_trace},
        )

    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "_engine_kind", "sqlite")
    await db.init_db()

    async with engine.connect() as conn:
        columns = {
            str(row[1])
            for row in (await conn.execute(text("PRAGMA table_info('decision_audit')")))
        }
        indexes = (
            await conn.execute(text("PRAGMA index_list('decision_audit')"))
        ).all()
        preserved = await conn.scalar(
            text("SELECT COUNT(*) FROM decision_audit WHERE id = :id"),
            {"id": old_id},
        )
    assert {
        "idempotency_key",
        "request_fingerprint",
        "idempotency_response",
    } <= columns
    assert any(
        bool(row[2]) and str(row[1]) == "uq_decision_audit_tenant_idempotency_key"
        for row in indexes
    )
    assert preserved == 1

    sessions = async_sessionmaker(engine, expire_on_commit=False)
    first_response = {"trace_id": str(uuid4()), "decision": "allow", "score": 0.0}
    async with sessions() as session:
        session.add(
            AuditRecord(
                trace_id=uuid4(),
                tenant_id="t1",
                entity_id="keyed-entity",
                event_type="payment",
                decision="allow",
                score=0.0,
                tags=[],
                rule_hits=[],
                payload_snapshot={},
                idempotency_key="startup-key",
                request_fingerprint="a" * 64,
                idempotency_response=first_response,
            )
        )
        session.add(
            AuditRecord(
                trace_id=uuid4(),
                tenant_id="t1",
                entity_id="legacy-null-key",
                event_type="payment",
                decision="allow",
                score=0.0,
                tags=[],
                rule_hits=[],
                payload_snapshot={},
            )
        )
        await session.commit()
        keyed = await session.scalar(
            select(AuditRecord).where(
                AuditRecord.tenant_id == "t1",
                AuditRecord.idempotency_key == "startup-key",
            )
        )
        assert keyed is not None
        assert json.loads(json.dumps(keyed.idempotency_response)) == first_response
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditRecord)
                .where(
                    AuditRecord.tenant_id == "t1",
                    AuditRecord.idempotency_key.is_(None),
                )
            )
            == 2
        )

    async with sessions() as session:
        session.add(
            AuditRecord(
                trace_id=uuid4(),
                tenant_id="t1",
                entity_id="duplicate-key",
                event_type="payment",
                decision="deny",
                score=100.0,
                tags=[],
                rule_hits=[],
                payload_snapshot={},
                idempotency_key="startup-key",
                request_fingerprint="b" * 64,
                idempotency_response={"decision": "deny"},
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    await db.init_db()
    await engine.dispose()
