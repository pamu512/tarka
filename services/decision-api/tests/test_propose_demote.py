"""Human-only Propose Demote → Confirm. Model never flips live off."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from decision_api.db import get_session
from decision_api.l2_draft import (
    L2DraftError,
    confirm_demote,
    is_forbidden_demote_actor,
    propose_demote,
)


class _EmptyResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _EmptySession:
    async def execute(self, *a, **k):
        return _EmptyResult()


def _live_pack(name: str = "live_pack") -> dict:
    return {
        "name": name,
        "mode": "active",
        "rules": [
            {
                "id": "r1",
                "when": [{"field": "amount", "op": "gt", "value": 0}],
                "score_delta": 5.0,
            }
        ],
        "tag_rules": [],
    }


def test_forbidden_demote_actors():
    assert is_forbidden_demote_actor("")
    assert is_forbidden_demote_actor("scout_coordinated_burst")
    assert is_forbidden_demote_actor("investigation-assist")
    assert is_forbidden_demote_actor("byom-llm")
    assert is_forbidden_demote_actor("llm")
    assert is_forbidden_demote_actor("vllm-local")
    assert is_forbidden_demote_actor("vertex-scout")
    assert not is_forbidden_demote_actor("ops-lead")
    assert not is_forbidden_demote_actor("analyst-web")
    assert not is_forbidden_demote_actor("web-ui")


def test_propose_demote_parks_without_flipping_mode():
    pack = _live_pack()
    out = propose_demote(pack, actor="ops-lead", reason="fp burst on live rule r1")
    assert out["mode"] == "active"
    blob = out["lifecycle"]["demote"]
    assert blob["state"] == "proposed"
    assert blob["proposed_by"] == "ops-lead"
    assert blob["proposed_reason"] == "fp burst on live rule r1"
    assert blob["proposed_at"]


def test_propose_demote_rejects_shadow_pack():
    pack = _live_pack()
    pack["mode"] = "shadow"
    with pytest.raises(L2DraftError) as ei:
        propose_demote(pack, actor="ops-lead", reason="already observe")
    assert ei.value.http_status == 409
    assert ei.value.code == "not_live"


def test_confirm_demote_requires_proposal_then_flips_shadow():
    pack = _live_pack()
    with pytest.raises(L2DraftError) as ei:
        confirm_demote(pack, actor="ops-lead", reason="confirm without propose")
    assert ei.value.http_status == 409
    assert ei.value.code == "demote_propose_first"

    propose_demote(pack, actor="ops-lead", reason="fp burst on live rule r1")
    out = confirm_demote(
        pack, actor="sec-lead", reason="human confirm retire to observe"
    )
    assert out["mode"] == "shadow"
    blob = out["lifecycle"]["demote"]
    assert blob["state"] == "confirmed"
    assert blob["confirmed_by"] == "sec-lead"
    assert blob["confirmed_reason"] == "human confirm retire to observe"


def _pack_body(name: str = "live_pack") -> dict:
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


async def _force_live(client, name: str = "live_pack") -> str:
    created = await client.post("/v1/rules", json=_pack_body(name))
    assert created.status_code == 201, created.text
    fname = created.json()["file"]
    ok = await client.post(
        f"/v1/rules/{fname}/force-live",
        json={"reason": "need live pack for demote tests"},
        headers={"X-Actor": "ops-lead"},
    )
    assert ok.status_code == 200, ok.text
    assert _on_disk(client, fname)["mode"] == "active"
    return fname


@pytest.mark.asyncio
async def test_human_propose_then_confirm_demote(client):
    fname = await _force_live(client, "human_demote")

    missing = await client.post(
        f"/v1/rules/{fname}/propose-demote",
        json={"reason": "fp burst on live rule r1"},
    )
    assert missing.status_code == 403, missing.text
    assert missing.json()["detail"] == "demote_human_only"
    assert _on_disk(client, fname)["mode"] == "active"

    short = await client.post(
        f"/v1/rules/{fname}/propose-demote",
        json={"reason": "short"},
        headers={"X-Actor": "ops-lead"},
    )
    assert short.status_code == 422, short.text
    assert _on_disk(client, fname)["mode"] == "active"

    proposed = await client.post(
        f"/v1/rules/{fname}/propose-demote",
        json={"reason": "fp burst on live rule r1"},
        headers={"X-Actor": "ops-lead"},
    )
    assert proposed.status_code == 200, proposed.text
    body = proposed.json()
    assert body["mode"] == "active"
    assert body["demote"]["state"] == "proposed"
    assert body["demote"]["proposed_by"] == "ops-lead"
    assert _on_disk(client, fname)["mode"] == "active"
    assert _on_disk(client, fname)["lifecycle"]["demote"]["state"] == "proposed"

    confirmed = await client.post(
        f"/v1/rules/{fname}/confirm-demote",
        json={"reason": "human confirm retire to observe"},
        headers={"X-Actor": "sec-lead"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["mode"] == "shadow"
    assert confirmed.json()["demote"]["state"] == "confirmed"
    assert _on_disk(client, fname)["mode"] == "shadow"

    log = await client.get("/v1/rules/change-log")
    actions = [
        item["action"] for item in log.json()["items"] if item.get("file") == fname
    ]
    assert "rule_propose_demote" in actions
    assert "rule_confirm_demote" in actions
    propose_row = next(
        item
        for item in log.json()["items"]
        if item.get("action") == "rule_propose_demote" and item.get("file") == fname
    )
    assert propose_row["actor"] == "ops-lead"
    assert propose_row["detail"]["reason"].startswith("fp burst")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "actor",
    [
        "scout_coordinated_burst",
        "investigation-assist",
        "byom-llm",
        "llm",
        "vllm-local",
    ],
)
async def test_model_paths_403_on_propose_and_confirm(client, actor):
    fname = await _force_live(client, f"model_{actor[:12]}")

    propose = await client.post(
        f"/v1/rules/{fname}/propose-demote",
        json={"reason": "model trying to park a demote"},
        headers={"X-Actor": actor},
    )
    assert propose.status_code == 403, propose.text
    assert propose.json()["detail"] == "demote_human_only"
    assert _on_disk(client, fname)["mode"] == "active"
    assert "demote" not in (_on_disk(client, fname).get("lifecycle") or {})

    human = await client.post(
        f"/v1/rules/{fname}/propose-demote",
        json={"reason": "human parks demote after model 403"},
        headers={"X-Actor": "ops-lead"},
    )
    assert human.status_code == 200, human.text

    confirm = await client.post(
        f"/v1/rules/{fname}/confirm-demote",
        json={"reason": "model trying to confirm demote"},
        headers={"X-Actor": actor},
    )
    assert confirm.status_code == 403, confirm.text
    assert confirm.json()["detail"] == "demote_human_only"
    assert _on_disk(client, fname)["mode"] == "active"


@pytest.mark.asyncio
async def test_confirm_without_propose_409_and_put_shadow_not_silent(client):
    fname = await _force_live(client, "no_silent")

    confirm = await client.post(
        f"/v1/rules/{fname}/confirm-demote",
        json={"reason": "confirm with no proposal parked"},
        headers={"X-Actor": "ops-lead"},
    )
    assert confirm.status_code == 409, confirm.text
    assert confirm.json()["detail"] == "demote_propose_first"
    assert _on_disk(client, fname)["mode"] == "active"

    put = await client.put(
        f"/v1/rules/{fname}/mode",
        json={"mode": "shadow"},
        headers={"X-Actor": "ops-lead"},
    )
    assert put.status_code == 409, put.text
    assert put.json()["detail"] == "demote_propose_first"
    assert _on_disk(client, fname)["mode"] == "active"

    scout_put = await client.put(
        f"/v1/rules/{fname}/mode",
        json={"mode": "shadow"},
        headers={"X-Actor": "scout_coordinated_burst"},
    )
    assert scout_put.status_code == 403, scout_put.text
    assert scout_put.json()["detail"] == "demote_human_only"
    assert _on_disk(client, fname)["mode"] == "active"
