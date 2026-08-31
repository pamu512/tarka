import json
from pathlib import Path

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


@pytest.fixture
async def rules_client(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    monkeypatch.delenv("RULE_GOVERNANCE_SECRET", raising=False)

    from auth_rbac import AuthUser
    from decision_api.config import settings
    from decision_api.rule_api import router as rules_router

    monkeypatch.setattr(settings, "rules_path", str(tmp_path))
    monkeypatch.setattr(settings, "rule_governance_secret", "")

    app = FastAPI()

    @app.middleware("http")
    async def _inject_auth(request, call_next):
        request.state.auth_user = AuthUser(
            "test-analyst", ["analyst", "admin"], "test", tenant_ids={"*"}
        )
        return await call_next(request)

    app.include_router(rules_router)

    async def _session_override():
        yield _EmptySession()

    app.dependency_overrides[get_session] = _session_override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client._rules_dir = tmp_path
        yield client
    app.dependency_overrides.clear()


def test_get_source_does_not_park():
    src = Path("src/decision_api/calibration_api.py").read_text(encoding="utf-8")
    # shadow_promote_gate function body only
    assert "maybe_park_live_rule_slip" not in src.split("async def shadow_promote_gate")[1].split("async def ")[0]


def test_tick_source_parks():
    src = Path("src/decision_api/calibration_api.py").read_text(encoding="utf-8")
    assert "maybe_park_live_rule_slip" in src


@pytest.mark.asyncio
async def test_get_returns_live_rule_slip_without_parking(
    challenge_client, tmp_path, monkeypatch
):
    from decision_api.config import settings

    monkeypatch.setattr(settings, "rules_path", str(tmp_path))
    r = await challenge_client.get("/v1/calibration/shadow-promote-gate")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["live_rule_slip"]["window"] in {"ok", "underpowered"}
    assert list(tmp_path.glob("slip_*.json")) == []


@pytest.mark.asyncio
async def test_scout_pack_slip_name_returns_409(rules_client, tmp_path, monkeypatch):
    from decision_api.json_rules import load_rules

    load_rules()
    r = await rules_client.post(
        "/v1/rules/scout-pack",
        json={
            "name": "slip_retire_r1",
            "mode": "shadow",
            "rules": [
                {
                    "id": "scout_r",
                    "when": [{"field": "amount", "op": "gt", "value": 0}],
                    "score_delta": 10.0,
                }
            ],
            "authored_by": "scout_coordinated_burst",
            "is_ai_authored": True,
        },
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "slip_draft_exists"
    assert list(tmp_path.glob("scout_*.json")) == []


def test_promote_slip_does_not_strip_live_rule(tmp_path, monkeypatch):
    from decision_api.config import settings
    from decision_api.json_rules import load_rules
    from decision_api.shadow_auto_promote import activate_shadow_pack

    monkeypatch.setattr(settings, "rules_path", str(tmp_path))
    (tmp_path / "live.json").write_text(
        json.dumps(
            {
                "version": 1,
                "name": "live",
                "mode": "active",
                "rules": [
                    {
                        "id": "r1",
                        "when": [{"field": "amount", "op": "gt", "value": 1}],
                        "score_delta": 20,
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (tmp_path / "slip_successor_r1.json").write_text(
        json.dumps(
            {
                "version": 1,
                "name": "slip_successor_r1",
                "mode": "shadow",
                "is_ai_authored": False,
                "authored_by": "slip_critic",
                "rules": [
                    {
                        "id": "slip_r1_DE",
                        "when": [{"field": "geo_country", "op": "eq", "value": "DE"}],
                        "score_delta": 15,
                    }
                ],
                "evidence": {
                    "slip_kind": "successor",
                    "live_rule_id": "r1",
                    "miss_is_not_recall": True,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    load_rules()
    out = activate_shadow_pack(
        "slip_successor_r1",
        actor="analyst",
        reason="promote_shadow_pack",
    )
    assert out["promoted"] is True
    assert out["mode"] == "active"
    live = json.loads((tmp_path / "live.json").read_text(encoding="utf-8"))
    assert any(str(r.get("id") or "") == "r1" for r in live["rules"])
    src = Path("src/decision_api/shadow_auto_promote.py").read_text(encoding="utf-8")
    activate_src = src.split("def activate_shadow_pack")[1].split("\nasync def ")[0].split("\ndef ")[0]
    assert "replaces_rule_id" not in activate_src
