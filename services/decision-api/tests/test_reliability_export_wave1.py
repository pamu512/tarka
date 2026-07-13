from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from decision_api.calibration_api import router as calibration_router
from decision_api.db import Base, get_session
from decision_api.models import AuditRecord
from decision_api.reliability_export import (
    audit_row_to_export_dict,
    proxy_label_from_decision,
    reliability_bins,
    rows_to_csv,
)


def test_proxy_label_from_decision():
    assert proxy_label_from_decision("block") == "1"
    assert proxy_label_from_decision("ALLOW") == "0"
    assert proxy_label_from_decision("weird") == ""


def test_rows_to_csv_and_bins():
    rows = [
        {
            "trace_id": uuid.uuid4(),
            "tenant_id": "acme",
            "entity_id": "e1",
            "event_type": "payment",
            "decision": "block",
            "score": 90.0,
            "payload_snapshot": {
                "inference_context": {
                    "integrity_confidence": 0.9,
                    "confidence_tier": "high",
                    "calibration_profile": "default",
                    "expected_calibration_version": 1,
                }
            },
            "created_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
        },
        {
            "trace_id": uuid.uuid4(),
            "tenant_id": "acme",
            "entity_id": "e2",
            "event_type": "payment",
            "decision": "allow",
            "score": 10.0,
            "payload_snapshot": {"inference_context": {"integrity_confidence": 0.1}},
            "created_at": datetime(2026, 7, 2, tzinfo=timezone.utc),
        },
    ]
    csv_body = rows_to_csv(rows)
    assert "proxy_label_from_decision" in csv_body
    assert "0.9" in csv_body
    export = [audit_row_to_export_dict(r) for r in rows]
    bins = reliability_bins(export, n_bins=5)
    assert bins["schema_id"] == "tarka.reliability_bins/v1"
    assert bins["labeled_rows"] == 2
    assert bins["proxy_label_rows"] == 2
    assert bins["caveat"]


def test_backtest_run_tombstone_in_source():
    """Avoid importing backtest_api (pulls analytics stack); assert the 410 tombstone shipped."""
    path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "decision_api"
        / "backtest_api.py"
    )
    src = path.read_text(encoding="utf-8")
    assert 'status_code=410' in src
    assert "BACKTEST_RUN_REMOVED" in src
    assert '@router.post("/run"' in src


@pytest.fixture
async def wave1_client(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'wave1.db'}")
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        session.add(
            AuditRecord(
                trace_id=uuid.uuid4(),
                tenant_id="acme-rel",
                entity_id="u1",
                event_type="payment",
                decision="block",
                score=88.0,
                tags=[],
                rule_hits=[],
                payload_snapshot={
                    "inference_context": {
                        "integrity_confidence": 0.88,
                        "confidence_tier": "high",
                    }
                },
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
        yield client

    await engine.dispose()


@pytest.mark.asyncio
async def test_reliability_export_endpoints(wave1_client):
    csv_r = await wave1_client.get(
        "/v1/calibration/reliability-export.csv",
        params={"tenant_id": "acme-rel", "limit": 100},
    )
    bins_r = await wave1_client.get(
        "/v1/calibration/reliability-bins",
        params={"tenant_id": "acme-rel", "limit": 100, "n_bins": 5},
    )

    assert csv_r.status_code == 200
    assert "text/csv" in (csv_r.headers.get("content-type") or "")
    assert "integrity_confidence" in csv_r.text
    assert "0.88" in csv_r.text

    assert bins_r.status_code == 200
    body = bins_r.json()
    assert body["schema_id"] == "tarka.reliability_bins/v1"
    assert body["labeled_rows"] >= 1
    assert body["tenant_id"] == "acme-rel"
