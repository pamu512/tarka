"""Parity-status ops surface (dual-diff proven vs dry_run)."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from decision_api.internal_counters_api import router as counters_router


@pytest.mark.asyncio
async def test_parity_status_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("COUNTER_PARITY_REPORT_PATH", str(tmp_path / "missing.json"))
    app = FastAPI()
    app.include_router(counters_router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/v1/internal/counters/parity-status")
    assert r.status_code == 200
    body = r.json()
    assert body["present"] is False
    assert body["dual_diff_proven"] is False


@pytest.mark.asyncio
async def test_parity_status_dual_diff_ok(tmp_path, monkeypatch):
    path = tmp_path / "parity.json"
    path.write_text(
        json.dumps(
            {
                "schema_id": "tarka.counter_parity/v1",
                "mode": "dual_diff",
                "matched": True,
                "events": 10,
                "ts": "2026-08-07T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("COUNTER_PARITY_REPORT_PATH", str(path))
    app = FastAPI()
    app.include_router(counters_router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/v1/internal/counters/parity-status")
    assert r.status_code == 200
    body = r.json()
    assert body["present"] is True
    assert body["dual_diff_proven"] is True
    assert body["ok"] is True
