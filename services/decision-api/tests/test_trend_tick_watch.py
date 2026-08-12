"""Trend watch + tick production path."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@pytest.fixture()
async def trend_http(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TREND_AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TREND_AGENT_DB_NAME", "trend_tick.sqlite3")
    monkeypatch.setenv("TREND_BASELINE_MIN_N", "3")
    monkeypatch.setenv("TREND_TICK_SKIP_LLM", "1")
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")

    from analytics import trend_store
    from auth_rbac import AuthUser
    from decision_api import trend_agent_api as tapi
    from decision_api.trend_agent_api import router as trend_router

    trend_store.reset_connection_for_tests()

    async def _fake_features(tenant_id: str, entity_id: str) -> dict[str, Any]:
        return {"event_count_5m": 50.0, "event_count_24h": 120.0}

    monkeypatch.setattr(tapi, "_features_for_entity", _fake_features)

    app = FastAPI()

    @app.middleware("http")
    async def _inject_auth(request, call_next):
        request.state.auth_user = AuthUser(
            "test-analyst", ["analyst"], "test", tenant_ids={"*"}
        )
        return await call_next(request)

    app.include_router(trend_router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    trend_store.reset_connection_for_tests()


@pytest.mark.asyncio
async def test_trend_posture(trend_http: AsyncClient) -> None:
    r = await trend_http.get("/v1/ops/trend/posture", params={"tenant_id": "ten-a"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema_id"] == "tarka.trend_ops_posture/v1"
    assert body["wasm_auto_promote"] is False
    assert body["tick_skip_llm_default"] is True


@pytest.mark.asyncio
async def test_watch_then_tick_creates_draft(trend_http: AsyncClient) -> None:
    w = await trend_http.post(
        "/v1/ops/trend/watch",
        json={"tenant_id": "ten-a", "entity_id": "ent-1", "reason": "test"},
    )
    assert w.status_code == 200, w.text

    # First ticks seed baselines only
    for _ in range(3):
        t = await trend_http.post(
            "/v1/ops/trend/tick",
            json={"tenant_id": "ten-a", "limit": 10, "skip_llm": True},
        )
        assert t.status_code == 200, t.text
        body = t.json()
        assert body["evaluated"] == 0
        assert body["skipped"] == 1

    # 4th tick evaluates
    t4 = await trend_http.post(
        "/v1/ops/trend/tick",
        json={"tenant_id": "ten-a", "limit": 10, "skip_llm": True},
    )
    assert t4.status_code == 200, t4.text
    body4 = t4.json()
    assert body4["evaluated"] == 1
    assert body4["results"][0]["status"] == "evaluated"
    assert body4["results"][0].get("draft_rule_id")

    drafts = await trend_http.get("/v1/ops/trend/drafts", params={"tenant_id": "ten-a"})
    assert drafts.status_code == 200
    assert drafts.json()["drafts"]
    assert drafts.json()["drafts"][0]["rule_package"].get("wasm_ready") is False
