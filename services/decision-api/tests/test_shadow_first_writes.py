"""Shadow-first API writes + human force-live (leftover HIL Task 9)."""

from __future__ import annotations

import json

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


def _pack_body(name: str = "hole_pack") -> dict:
    return {
        "name": name,
        "rules": [
            {
                "id": "r1",
                "when": [{"field": "amount", "op": "gt", "value": 0}],
                "score_delta": 5.0,
            }
        ],
        "tag_rules": [],
    }


@pytest.fixture
async def client(tmp_path, monkeypatch):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    monkeypatch.setenv("RULES_PATH", str(rules_dir))

    from auth_rbac import AuthUser
    from decision_api.config import settings
    from decision_api.rule_api import router as rules_router

    monkeypatch.setattr(settings, "rules_path", str(rules_dir))

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
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c._rules_dir = rules_dir
        yield c
    app.dependency_overrides.clear()


def _on_disk(client, filename: str) -> dict:
    return json.loads((client._rules_dir / filename).read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_create_and_update_persist_shadow(client):
    created = await client.post("/v1/rules", json=_pack_body("create_hole"))
    assert created.status_code == 201, created.text
    fname = created.json()["file"]
    assert _on_disk(client, fname)["mode"] == "shadow"
    assert created.json()["pack"]["mode"] == "shadow"

    (client._rules_dir / fname).write_text(
        json.dumps({**_on_disk(client, fname), "mode": "active"}, indent=2),
        encoding="utf-8",
    )
    assert _on_disk(client, fname)["mode"] == "active"

    updated = await client.put(f"/v1/rules/{fname}", json=_pack_body("create_hole"))
    assert updated.status_code == 200, updated.text
    assert _on_disk(client, fname)["mode"] == "shadow"
    assert updated.json()["pack"]["mode"] == "shadow"

    added = await client.post(
        f"/v1/rules/{fname}/rules",
        json={
            "id": "r2",
            "when": [{"field": "amount", "op": "gt", "value": 10}],
            "score_delta": 6.0,
        },
    )
    assert added.status_code == 200, added.text
    (client._rules_dir / fname).write_text(
        json.dumps({**_on_disk(client, fname), "mode": "active"}, indent=2),
        encoding="utf-8",
    )
    added2 = await client.post(
        f"/v1/rules/{fname}/rules",
        json={
            "id": "r3",
            "when": [{"field": "amount", "op": "gt", "value": 20}],
            "score_delta": 7.0,
        },
    )
    assert added2.status_code == 200, added2.text
    assert _on_disk(client, fname)["mode"] == "shadow"


@pytest.mark.asyncio
async def test_force_live_requires_actor_and_reason(client):
    created = await client.post("/v1/rules", json=_pack_body("force_live_pack"))
    assert created.status_code == 201, created.text
    fname = created.json()["file"]

    missing_actor = await client.post(
        f"/v1/rules/{fname}/force-live",
        json={"reason": "emergency live hop for incident 42"},
    )
    assert missing_actor.status_code == 403, missing_actor.text
    assert missing_actor.json()["detail"] == "force_live_human_only"
    assert _on_disk(client, fname)["mode"] == "shadow"

    short = await client.post(
        f"/v1/rules/{fname}/force-live",
        json={"reason": "short"},
        headers={"X-Actor": "ops-lead"},
    )
    assert short.status_code == 422, short.text
    assert _on_disk(client, fname)["mode"] == "shadow"

    scout = await client.post(
        f"/v1/rules/{fname}/force-live",
        json={"reason": "scout trying to skip leftover gates"},
        headers={"X-Actor": "scout_coordinated_burst"},
    )
    assert scout.status_code == 403, scout.text
    assert scout.json()["detail"] == "force_live_human_only"
    assert _on_disk(client, fname)["mode"] == "shadow"

    assist = await client.post(
        f"/v1/rules/{fname}/force-live",
        json={"reason": "assist trying to skip leftover gates"},
        headers={"X-Actor": "investigation-assist"},
    )
    assert assist.status_code == 403, assist.text
    assert assist.json()["detail"] == "force_live_human_only"

    ok = await client.post(
        f"/v1/rules/{fname}/force-live",
        json={"reason": "incident-42 leftover queue is empty and we need live"},
        headers={"X-Actor": "ops-lead"},
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["mode"] == "active"
    assert body["forced"] is True
    assert body["file"] == fname
    assert _on_disk(client, fname)["mode"] == "active"

    log = await client.get("/v1/rules/change-log")
    assert log.status_code == 200, log.text
    row = next(
        item
        for item in log.json()["items"]
        if item.get("action") == "rule_force_live" and item.get("file") == fname
    )
    assert row["actor"] == "ops-lead"
    assert row["detail"]["reason"].startswith("incident-42")
    assert row["detail"]["prior_mode"] == "shadow"
    assert row["detail"]["file"] == fname


@pytest.mark.asyncio
async def test_force_live_two_person_requires_distinct_approver(client, monkeypatch):
    monkeypatch.setenv("RULE_FORCE_LIVE_TWO_PERSON", "1")
    created = await client.post("/v1/rules", json=_pack_body("two_person_pack"))
    assert created.status_code == 201, created.text
    fname = created.json()["file"]

    missing = await client.post(
        f"/v1/rules/{fname}/force-live",
        json={"reason": "incident-99 need live with maker checker"},
        headers={"X-Actor": "ops-lead"},
    )
    assert missing.status_code == 403, missing.text
    assert missing.json()["detail"] == "force_live_approver_required"
    assert _on_disk(client, fname)["mode"] == "shadow"

    same = await client.post(
        f"/v1/rules/{fname}/force-live",
        json={"reason": "incident-99 need live with maker checker"},
        headers={"X-Actor": "ops-lead", "X-Force-Live-Approver": "ops-lead"},
    )
    assert same.status_code == 403, same.text
    assert same.json()["detail"] == "force_live_approver_must_differ"

    scout_approver = await client.post(
        f"/v1/rules/{fname}/force-live",
        json={"reason": "incident-99 need live with maker checker"},
        headers={
            "X-Actor": "ops-lead",
            "X-Force-Live-Approver": "scout_bot",
        },
    )
    assert scout_approver.status_code == 403, scout_approver.text
    assert scout_approver.json()["detail"] == "force_live_human_only"

    ok = await client.post(
        f"/v1/rules/{fname}/force-live",
        json={"reason": "incident-99 need live with maker checker"},
        headers={
            "X-Actor": "ops-lead",
            "X-Force-Live-Approver": "sec-lead",
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["approver"] == "sec-lead"
    assert _on_disk(client, fname)["mode"] == "active"

    log = await client.get("/v1/rules/change-log")
    row = next(
        item
        for item in log.json()["items"]
        if item.get("action") == "rule_force_live" and item.get("file") == fname
    )
    assert row["detail"]["approver"] == "sec-lead"


@pytest.mark.asyncio
async def test_put_mode_active_is_shadow_first(client, monkeypatch):
    created = await client.post("/v1/rules", json=_pack_body("quiet_active"))
    assert created.status_code == 201, created.text
    fname = created.json()["file"]

    async def _fetch(_tenant_id: str):
        return []

    monkeypatch.setattr(
        "decision_api.leftover_promote_gate.fetch_leftover_list", _fetch
    )

    r = await client.put(
        f"/v1/rules/{fname}/mode",
        params={"tenant_id": "t1"},
        json={"mode": "active"},
        headers={"X-Actor": "ops-lead"},
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "shadow_first"
    assert _on_disk(client, fname)["mode"] == "shadow"
