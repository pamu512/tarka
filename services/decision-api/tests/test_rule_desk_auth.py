"""Insecure-desk analyst parity for rule_api promote/provision routes (walkthrough B3).

The rules.md local journey is expected to promote a shadow draft into live. On an
ALLOW_INSECURE_NO_AUTH desk the anonymous user holds viewer only, so
require_role("analyst") 403s and the documented journey dead-ends. House idiom
(require_role_or_insecure_desk, see auth_rbac) permits anonymous local desks to act
while production fail-closes. Admin routes must stay strictly admin.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

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
async def anon_client(monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    monkeypatch.delenv("API_KEYS", raising=False)
    monkeypatch.delenv("RULE_GOVERNANCE_SECRET", raising=False)

    from auth_rbac import AuthUser

    from decision_api.rule_api import router as rule_router

    app = FastAPI()

    # Mirror the real app middleware on an insecure desk: anonymous viewer.
    @app.middleware("http")
    async def _anon_auth(request, call_next):
        request.state.auth_user = AuthUser(
            "anonymous", ["viewer"], "none", tenant_ids=set()
        )
        return await call_next(request)

    app.include_router(rule_router)

    async def _session_override():
        yield _EmptySession()

    app.dependency_overrides[get_session] = _session_override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_anonymous_insecure_desk_can_read_promote_posture(anon_client):
    r = await anon_client.get("/v1/rules/backtest-before-promote-posture")
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_anonymous_insecure_desk_can_promote_shadow_pack(anon_client, tmp_path, monkeypatch):
    monkeypatch.setenv("TARKA_RULES_DIR", str(tmp_path))
    r = await anon_client.post("/v1/rules/shadow-packs/does-not-exist/promote?tenant_id=t1")
    assert r.status_code != 403, (
        "insecure desk anonymous must not 403 on promote (got "
        f"{r.status_code}: {r.text[:200]})"
    )


@pytest.mark.asyncio
async def test_anonymous_insecure_desk_can_get_provision(anon_client):
    r = await anon_client.get("/v1/rules/shadow-auto-promote-provision?tenant_id=t1")
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_anonymous_insecure_desk_can_put_provision(anon_client):
    r = await anon_client.put(
        "/v1/rules/shadow-auto-promote-provision",
        json={"enabled": True},
    )
    assert r.status_code != 403, (
        f"insecure desk anonymous must not 403 on provision PUT (got {r.status_code})"
    )


@pytest.mark.asyncio
async def test_admin_reload_stays_admin_only(anon_client):
    r = await anon_client.post("/v1/rules/shadow/reload")
    assert r.status_code == 403, "shadow/reload must stay strictly admin-gated"
