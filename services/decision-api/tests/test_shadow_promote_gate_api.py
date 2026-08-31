"""GET /v1/calibration/shadow-promote-gate contract (Fraud Ops 4.2 + P0-CC)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from decision_api.calibration_api import router as calibration_router
from decision_api.db import get_session


class _EmptyResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _EmptySession:
    async def execute(self, *a, **k):
        return _EmptyResult()


@pytest.fixture
async def challenge_client(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")

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
        yield _EmptySession()

    app.dependency_overrides[get_session] = _session_override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_shadow_promote_gate_endpoint(challenge_client):
    r = await challenge_client.get("/v1/calibration/shadow-promote-gate")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema_id"] == "tarka.shadow_promote_gate/v1"
    assert body["blocked"]["promote_allowed"] is False
    assert body["allowed"]["promote_allowed"] is True
    assert "shadow_vs_primary_diff_recipe.sql" in body["recipe_path"]
    assert body["label_gated_promote"]["promote_allowed"] is False
    assert body["mcnemar_promote_gate"]["promote_allowed"] is False
    assert "drift_promote_gate" in body
    assert body["desk_promote_gate"]["promote_allowed"] is False
    assert "drift_promote_gate" in (body["desk_promote_gate"].get("requires") or [])
    assert "champion_challenger" in body
    assert (
        body["champion_challenger"]["schema_id"] == "tarka.champion_challenger_audit/v1"
    )
    assert "rule_precision_after_labels" in body
    assert (
        body["rule_precision_after_labels"]["schema_id"]
        == "tarka.rule_precision_after_labels/v1"
    )


@pytest.mark.asyncio
async def test_shadow_promote_gate_includes_leftover_gate(challenge_client, monkeypatch):
    monkeypatch.setattr("decision_api.config.settings.case_api_url", "")
    r = await challenge_client.get("/v1/calibration/shadow-promote-gate")
    assert r.status_code == 200
    body = r.json()
    assert body["leftover_promote_gate"]["schema_id"] == "tarka.leftover_promote_gate/v1"
    assert "leftover_queue_unavailable" in body["leftover_promote_gate"]["blockers"]
    assert "leftover_promote_gate" in body["desk_promote_gate"]["requires"]
    assert body["desk_promote_gate"]["promote_allowed"] is False
    assert isinstance(body.get("shadow_drafts"), list)


@pytest.mark.asyncio
async def test_shadow_promote_gate_extras_use_full_cc_scan(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    monkeypatch.setattr("decision_api.config.settings.case_api_url", "")

    from auth_rbac import AuthUser
    from decision_api.calibration_api import router as calibration_router
    from decision_api.db import get_session

    class _Rec:
        def __init__(self, i: int):
            self.trace_id = f"t{i:03d}"
            self.tenant_id = "acme"
            self.entity_id = f"e{i:03d}"
            self.event_type = "payment"
            self.decision = "allow"
            self.score = 0.1
            self.rule_hits = []
            self.payload_snapshot = {
                "policy_routing": {
                    "champion_decision": "allow",
                    "challenger_decision": "review",
                }
            }
            self.created_at = None

    class _ManyResult:
        def scalars(self):
            return self

        def all(self):
            return [_Rec(i) for i in range(60)]

    class _ManySession:
        async def execute(self, *a, **k):
            return _ManyResult()

    app = FastAPI()

    @app.middleware("http")
    async def _inject_auth(request, call_next):
        request.state.auth_user = AuthUser(
            "test-analyst", ["analyst", "admin"], "test", tenant_ids={"*"}
        )
        return await call_next(request)

    app.include_router(calibration_router)

    async def _session_override():
        yield _ManySession()

    app.dependency_overrides[get_session] = _session_override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            "/v1/calibration/shadow-promote-gate", params={"tenant_id": "acme"}
        )
    app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["leftover_promote_gate"]["extra_review_or_deny"] == 60
    assert len(body["champion_challenger"]["audit_rows"]) == 50


@pytest.mark.asyncio
async def test_shadow_promote_gate_get_does_not_auto_promote(challenge_client, monkeypatch):
    writes: list[str] = []

    def _record(name: str):
        def _inner(*_a, **_k):
            writes.append(name)

        return _inner

    monkeypatch.setattr(
        "decision_api.leftover_promote_gate.maybe_auto_promote",
        _record("maybe_auto_promote"),
        raising=False,
    )
    r = await challenge_client.get(
        "/v1/calibration/shadow-promote-gate", params={"tenant_id": "acme"}
    )
    assert r.status_code == 200, r.text
    assert writes == []
