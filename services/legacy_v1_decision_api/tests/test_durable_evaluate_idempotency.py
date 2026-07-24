from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from decision_api import evaluate_idempotency as idem
from decision_api.db import Base
from decision_api.models import AuditRecord
from decision_api.schemas import EvaluateResponse
from tarka_core.cache import LocalDictCache


def _payload(*, entity_id: str = "entity-1") -> dict:
    return {
        "tenant_id": "t1",
        "event_type": "payment",
        "entity_id": entity_id,
        "payload": {"amount": 100},
    }


def _response() -> EvaluateResponse:
    return EvaluateResponse(
        trace_id=uuid4(),
        decision="allow",
        score=0.0,
        tags=[],
        inference_context={},
    )


@pytest.fixture
async def durable_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from decision_api import main as main_mod
    from decision_api.main import app, get_session

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'audit.sqlite3'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _session_override():
        async with sessions() as session:
            yield session

    unavailable_store = SimpleNamespace(
        connect=AsyncMock(),
        _client=None,
        _kv=None,
        _async_lock=asyncio.Lock(),
    )
    monkeypatch.setattr(idem, "redis_tags", unavailable_store)
    monkeypatch.setenv("API_KEYS", "test-key")
    monkeypatch.setenv("API_KEY_TENANT_MAP", '{"test-key":["t1"]}')
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
    app.dependency_overrides[get_session] = _session_override

    async def _evaluate(body, request, _bg, session):
        response = _response()
        audit = AuditRecord(
            trace_id=response.trace_id,
            tenant_id=body.tenant_id,
            entity_id=body.entity_id,
            event_type=body.event_type.value,
            decision=response.decision,
            score=response.score,
            tags=response.tags,
            rule_hits=response.rule_hits,
            payload_snapshot={},
        )
        session.add(audit)
        replay = await main_mod._commit_authoritative_audit(
            request,
            session,
            audit=audit,
            response=response,
        )
        return replay or response

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"x-api-key": "test-key"},
    ) as client:
        yield client, sessions, _evaluate

    app.dependency_overrides.pop(get_session, None)
    await engine.dispose()


@pytest.mark.asyncio
async def test_redis_loss_concurrency_has_one_durable_audit_and_stable_response(
    durable_client,
):
    client, sessions, evaluator = durable_client
    with patch(
        "decision_api.main._evaluate_decision_impl",
        new=AsyncMock(side_effect=evaluator),
    ):
        first, second = await asyncio.gather(
            client.post(
                "/v1/decisions/evaluate",
                headers={"Idempotency-Key": "durable-concurrent"},
                json=_payload(),
            ),
            client.post(
                "/v1/decisions/evaluate",
                headers={"Idempotency-Key": "durable-concurrent"},
                json=_payload(),
            ),
        )

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    async with sessions() as session:
        count = await session.scalar(select(func.count()).select_from(AuditRecord))
    assert count == 1


@pytest.mark.asyncio
async def test_durable_key_rejects_different_fingerprint(durable_client):
    client, sessions, evaluator = durable_client
    with patch(
        "decision_api.main._evaluate_decision_impl",
        new=AsyncMock(side_effect=evaluator),
    ) as evaluation:
        first = await client.post(
            "/v1/decisions/evaluate",
            headers={"Idempotency-Key": "durable-mismatch"},
            json=_payload(),
        )
        mismatch = await client.post(
            "/v1/decisions/evaluate",
            headers={"Idempotency-Key": "durable-mismatch"},
            json=_payload(entity_id="entity-2"),
        )

    assert first.status_code == 200
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["error"] == "evaluate_idempotency_payload_mismatch"
    assert evaluation.await_count == 1
    async with sessions() as session:
        count = await session.scalar(select(func.count()).select_from(AuditRecord))
    assert count == 1


@pytest.mark.asyncio
async def test_completion_store_failure_returns_durable_response(
    durable_client, monkeypatch
):
    client, _sessions, evaluator = durable_client
    cache = LocalDictCache()
    monkeypatch.setattr(
        idem,
        "redis_tags",
        SimpleNamespace(
            connect=AsyncMock(),
            _client=None,
            _kv=cache,
            _async_lock=asyncio.Lock(),
        ),
    )
    with (
        patch(
            "decision_api.main._evaluate_decision_impl",
            new=AsyncMock(side_effect=evaluator),
        ) as evaluation,
        patch(
            "decision_api.evaluate_idempotency.complete_evaluate_idempotency",
            new=AsyncMock(side_effect=TimeoutError("completion unavailable")),
        ),
    ):
        first = await client.post(
            "/v1/decisions/evaluate",
            headers={"Idempotency-Key": "durable-completion"},
            json=_payload(),
        )
        retry = await client.post(
            "/v1/decisions/evaluate",
            headers={"Idempotency-Key": "durable-completion"},
            json=_payload(),
        )

    assert first.status_code == retry.status_code == 200
    assert first.json() == retry.json()
    assert evaluation.await_count == 1


@pytest.mark.asyncio
async def test_ambiguous_commit_reconstructs_durable_response(durable_client):
    from decision_api import main as main_mod

    client, sessions, _evaluator = durable_client

    async def _ambiguous_evaluation(body, request, _bg, session):
        response = _response()
        audit = AuditRecord(
            trace_id=response.trace_id,
            tenant_id=body.tenant_id,
            entity_id=body.entity_id,
            event_type=body.event_type.value,
            decision=response.decision,
            score=response.score,
            tags=[],
            rule_hits=[],
            payload_snapshot={},
        )
        session.add(audit)
        real_commit = session.commit

        async def _ambiguous_commit():
            await real_commit()
            raise TimeoutError("commit acknowledgement lost")

        session.commit = _ambiguous_commit
        replay = await main_mod._commit_authoritative_audit(
            request,
            session,
            audit=audit,
            response=response,
        )
        return replay or response

    with patch(
        "decision_api.main._evaluate_decision_impl",
        new=AsyncMock(side_effect=_ambiguous_evaluation),
    ):
        result = await client.post(
            "/v1/decisions/evaluate",
            headers={"Idempotency-Key": "durable-ambiguous"},
            json=_payload(),
        )

    assert result.status_code == 200, result.text
    async with sessions() as session:
        rows = (await session.scalars(select(AuditRecord))).all()
    assert len(rows) == 1
    assert rows[0].idempotency_response == result.json()
