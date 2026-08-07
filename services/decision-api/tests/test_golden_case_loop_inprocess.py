"""Wave 5: in-process golden loop (evaluate substitute = audit row + y_label join)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from decision_api.calibration_api import router as calibration_router
from decision_api.db import Base, get_session
from decision_api.models import AuditRecord


@pytest.fixture
async def golden_client(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'golden.db'}")
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    tid = uuid.uuid4()
    async with session_factory() as session:
        session.add(
            AuditRecord(
                trace_id=tid,
                tenant_id="golden-tenant",
                entity_id="golden-entity",
                event_type="payment",
                decision="allow",
                score=22.0,
                tags=[],
                rule_hits=[],
                payload_snapshot={
                    "inference_context": {
                        "integrity_confidence": 0.91,
                        "confidence_tier": "high",
                    }
                },
                created_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    from auth_rbac import AuthUser

    app = FastAPI()

    @app.middleware("http")
    async def _inject_auth(request, call_next):
        request.state.auth_user = AuthUser(
            "test-analyst", ["analyst", "admin"], "test", tenant_ids={"*"}
        )
        return await call_next(request)

    app.include_router(calibration_router)

    async def _session_override():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = _session_override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, str(tid)

    await engine.dispose()


@pytest.mark.asyncio
async def test_golden_y_label_post_is_healthy(golden_client):
    client, trace_id = golden_client
    r = await client.post(
        "/v1/calibration/reliability-bins",
        params={"tenant_id": "golden-tenant", "n_bins": 5, "limit": 100},
        json={
            "labels_by_trace": {trace_id: "LEGITIMATE"},
            "allow_proxy_labels": False,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    posture = body.get("posture") or {}
    assert posture.get("healthy") is True, body
    assert (
        float(body.get("label_coverage") or posture.get("label_coverage") or 0) >= 0.2
    )
