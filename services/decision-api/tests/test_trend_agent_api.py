"""Trend agent ops HTTP surface: evaluate / reject / never promote."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@pytest.fixture()
async def trend_http(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TREND_AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TREND_AGENT_DB_NAME", "trend_http.sqlite3")
    monkeypatch.setenv("TREND_AGENT_SKIP_LLM", "1")
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")

    from analytics import trend_store
    from auth_rbac import AuthUser
    from decision_api.trend_agent_api import router as trend_router

    trend_store.reset_connection_for_tests()
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
async def test_trend_http_evaluate_reject_promote_forbidden(
    trend_http: AsyncClient,
) -> None:
    empty = await trend_http.post(
        "/v1/ops/trend/evaluate",
        json={
            "tenant_id": "ten-a",
            "entity_id": "ent-1",
            "window_rows": [],
            "skip_llm": True,
        },
    )
    assert empty.status_code == 400
    assert empty.json()["detail"]["error"] == "window_rows_required"

    rows = [
        {
            "metric_key": "sub_1min_velocity",
            "window": "sub_1min",
            "observed": 100.0,
            "baseline_mean": 10.0,
            "baseline_std": 2.0,
        }
    ]
    r = await trend_http.post(
        "/v1/ops/trend/evaluate",
        json={
            "tenant_id": "ten-a",
            "entity_id": "ent-1",
            "window_rows": rows,
            "skip_llm": True,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["disposition"] == "ESCALATED"
    draft_id = body["draft_rule_id"]
    assert draft_id

    listed = await trend_http.get("/v1/ops/trend/drafts", params={"tenant_id": "ten-a"})
    assert listed.status_code == 200
    drafts = listed.json()["drafts"]
    assert any(d["id"] == draft_id for d in drafts)
    pkg = next(d["rule_package"] for d in drafts if d["id"] == draft_id)
    assert pkg.get("wasm_ready") is False
    assert pkg.get("promotable") is False

    # Tenant isolation: other tenant sees no drafts
    other = await trend_http.get(
        "/v1/ops/trend/drafts", params={"tenant_id": "ten-other"}
    )
    assert other.status_code == 200
    assert other.json()["drafts"] == []

    banned = await trend_http.post(
        f"/v1/ops/trend/drafts/{draft_id}/promote",
        params={"tenant_id": "ten-a"},
    )
    assert banned.status_code == 409
    assert banned.json()["detail"]["error"] == "never_auto_promote"

    rejected = await trend_http.post(
        f"/v1/ops/trend/drafts/{draft_id}/reject",
        params={"tenant_id": "ten-a"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["draft"]["status"] == "REJECTED"

    # Rejected draft no longer listed as pending
    listed2 = await trend_http.get(
        "/v1/ops/trend/drafts", params={"tenant_id": "ten-a"}
    )
    assert all(d["id"] != draft_id for d in listed2.json()["drafts"])


@pytest.mark.asyncio
async def test_trend_http_viewer_forbidden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TREND_AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TREND_AGENT_DB_NAME", "trend_http_viewer.sqlite3")
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    from analytics import trend_store
    from auth_rbac import AuthUser
    from decision_api.trend_agent_api import router as trend_router

    trend_store.reset_connection_for_tests()
    app = FastAPI()

    @app.middleware("http")
    async def _inject_auth(request, call_next):
        request.state.auth_user = AuthUser(
            "viewer", ["viewer"], "test", tenant_ids={"*"}
        )
        return await call_next(request)

    app.include_router(trend_router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/v1/ops/trend/evaluate",
            json={
                "tenant_id": "ten-a",
                "entity_id": "ent-1",
                "window_rows": [
                    {
                        "metric_key": "sub_1min_velocity",
                        "window": "sub_1min",
                        "observed": 1,
                        "baseline_mean": 1,
                        "baseline_std": 1,
                    }
                ],
            },
        )
        assert r.status_code == 403
    trend_store.reset_connection_for_tests()


@pytest.mark.asyncio
async def test_tick_enqueues_agent_run_and_survives_agent_down(
    trend_http: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INVESTIGATION_AGENT_URL", "http://inv.test")
    posted: list[dict] = []

    async def _fake_post(url, json=None, headers=None, timeout=None):  # noqa: ANN001
        posted.append({"url": url, "json": json})
        raise RuntimeError("down")

    import httpx
    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    # Direct evaluate still 200; enqueue helper must not raise.
    from decision_api.trend_agent_api import maybe_enqueue_trend_agent_run

    await maybe_enqueue_trend_agent_run(
        tenant_id="ten-a",
        entity_id="ent-1",
        turn_id="trend:ent-1",
        context_snapshot={"freshness": {"graph": "missing"}},
        claims=[],
    )
