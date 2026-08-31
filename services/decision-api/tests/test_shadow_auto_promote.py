"""Shadow auto-promote provision file store + HTTP (leftover HIL Task 5–6)."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from decision_api.db import get_session


def test_provision_default_then_save_increments(tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    from decision_api.shadow_auto_promote import default_provision, load_provision, save_provision

    d = default_provision("t1")
    assert d["auto_promote"] is False
    assert d["version"] == 0
    assert d["leftover_add_cap"] == 10
    assert d["leftover_fp_rate_cap"] == 0.4
    assert d["min_labeled_extras"] == 5
    assert load_provision("t1")["version"] == 0
    s = save_provision(
        "t1",
        auto_promote=True,
        leftover_add_cap=3,
        leftover_fp_rate_cap=0.2,
        min_labeled_extras=6,
        provisioned_by="ops",
    )
    assert s["version"] == 1
    assert s["auto_promote"] is True
    assert s["leftover_add_cap"] == 3
    assert load_provision("t1")["version"] == 1
    s2 = save_provision(
        "t1",
        auto_promote=True,
        leftover_add_cap=0,
        leftover_fp_rate_cap=0.2,
        min_labeled_extras=6,
        provisioned_by="ops",
    )
    assert s2["version"] == 2
    assert s2["leftover_add_cap"] == 0


def test_save_provision_rejects_invalid_caps(tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    from decision_api.shadow_auto_promote import save_provision

    with pytest.raises(ValueError):
        save_provision(
            "t1",
            auto_promote=True,
            leftover_add_cap=-1,
            leftover_fp_rate_cap=0.2,
            min_labeled_extras=5,
            provisioned_by="ops",
        )
    with pytest.raises(ValueError):
        save_provision(
            "t1",
            auto_promote=True,
            leftover_add_cap=1,
            leftover_fp_rate_cap=1.1,
            min_labeled_extras=5,
            provisioned_by="ops",
        )
    with pytest.raises(ValueError):
        save_provision(
            "t1",
            auto_promote=True,
            leftover_add_cap=1,
            leftover_fp_rate_cap=-0.01,
            min_labeled_extras=5,
            provisioned_by="ops",
        )
    with pytest.raises(ValueError):
        save_provision(
            "t1",
            auto_promote=True,
            leftover_add_cap=1,
            leftover_fp_rate_cap=0.2,
            min_labeled_extras=0,
            provisioned_by="ops",
        )


def test_provision_filename_is_content_addressed(tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    from decision_api.shadow_auto_promote import save_provision

    tenant = "evil-tenant"
    save_provision(
        tenant,
        auto_promote=False,
        leftover_add_cap=10,
        leftover_fp_rate_cap=0.4,
        min_labeled_extras=5,
        provisioned_by="ops",
    )
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    name = files[0].name
    assert name.startswith("shadow_auto_promote_")
    assert name.endswith(".json")
    assert tenant not in name
    assert "evil" not in name


def test_provision_caps_win_over_env_when_version_ge_1(tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LEFTOVER_PROMOTE_ADD_CAP", "99")
    monkeypatch.setenv("LEFTOVER_PROMOTE_FP_RATE_CAP", "0.9")
    monkeypatch.setenv("LEFTOVER_PROMOTE_MIN_LABELED_EXTRAS", "20")
    from decision_api.leftover_promote_gate import leftover_caps_for_tenant
    from decision_api.shadow_auto_promote import save_provision

    add, fp, mn = leftover_caps_for_tenant("t1")
    assert (add, fp, mn) == (99, 0.9, 20)
    save_provision(
        "t1",
        auto_promote=False,
        leftover_add_cap=3,
        leftover_fp_rate_cap=0.2,
        min_labeled_extras=6,
        provisioned_by="ops",
    )
    add, fp, mn = leftover_caps_for_tenant("t1")
    assert (add, fp, mn) == (3, 0.2, 6)


@pytest.fixture
async def provision_client(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(tmp_path))

    from auth_rbac import AuthUser
    from decision_api.rule_api import router as rules_router

    app = FastAPI()

    @app.middleware("http")
    async def _inject_auth(request, call_next):
        request.state.auth_user = AuthUser(
            "test-analyst", ["analyst", "admin"], "test", tenant_ids={"*"}
        )
        return await call_next(request)

    app.include_router(rules_router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_http_get_never_provisioned_returns_defaults(provision_client):
    r = await provision_client.get(
        "/v1/rules/shadow-auto-promote-provision",
        params={"tenant_id": "t1"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema_id"] == "tarka.shadow_auto_promote_provision/v1"
    assert body["auto_promote"] is False
    assert body["version"] == 0
    assert body["leftover_add_cap"] == 10
    assert body["leftover_fp_rate_cap"] == 0.4
    assert body["min_labeled_extras"] == 5


@pytest.mark.asyncio
async def test_http_put_sets_provisioned_by_from_x_actor(provision_client):
    r = await provision_client.put(
        "/v1/rules/shadow-auto-promote-provision",
        json={
            "tenant_id": "t1",
            "auto_promote": True,
            "leftover_add_cap": 3,
            "leftover_fp_rate_cap": 0.2,
            "min_labeled_extras": 6,
        },
        headers={"X-Actor": "ops-lead"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == 1
    assert body["auto_promote"] is True
    assert body["leftover_add_cap"] == 3
    assert body["provisioned_by"] == "ops-lead"
    assert body["provisioned_at"]
    got = await provision_client.get(
        "/v1/rules/shadow-auto-promote-provision",
        params={"tenant_id": "t1"},
    )
    assert got.json()["version"] == 1
    assert got.json()["provisioned_by"] == "ops-lead"


@pytest.mark.asyncio
async def test_http_put_provisioned_by_falls_back_to_user_id(provision_client):
    r = await provision_client.put(
        "/v1/rules/shadow-auto-promote-provision",
        json={
            "tenant_id": "t2",
            "auto_promote": False,
            "leftover_add_cap": 10,
            "leftover_fp_rate_cap": 0.4,
            "min_labeled_extras": 5,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["provisioned_by"] == "test-analyst"
    assert r.json()["version"] == 1


class _EmptyResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _EmptySession:
    async def execute(self, *a, **k):
        return _EmptyResult()


def _write_shadow_pack(rules_dir, *, name: str, filename: str, is_ai_authored: bool = True):
    path = rules_dir / filename
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "name": name,
                "mode": "shadow",
                "is_ai_authored": is_ai_authored,
                "rules": [
                    {
                        "id": "r1",
                        "when": [{"field": "amount", "op": "gt", "value": 0}],
                        "score_delta": 1.0,
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _patch_leftover_fetch(monkeypatch, leftovers):
    async def _fetch(tenant_id: str):
        return leftovers

    monkeypatch.setattr(
        "decision_api.leftover_promote_gate.fetch_leftover_list", _fetch
    )

    async def _ack(tenant_id: str, draft_id: str):
        return None

    monkeypatch.setattr("decision_api.leftover_promote_gate.fetch_promote_ack", _ack)


def _patch_desk_science_green(monkeypatch):
    def _green(*_a, **_k):
        return {"promote_allowed": True, "blockers": []}

    monkeypatch.setattr(
        "decision_api.champion_challenger_audit.label_gated_promote", _green
    )
    monkeypatch.setattr(
        "decision_api.champion_challenger_audit.mcnemar_promote_gate", _green
    )
    monkeypatch.setattr(
        "decision_api.champion_challenger_audit.drift_promote_gate", _green
    )


@pytest.fixture
async def desk_client(tmp_path, monkeypatch):
    rules_dir = tmp_path / "rules"
    cal_dir = tmp_path / "cal"
    rules_dir.mkdir()
    cal_dir.mkdir()
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(cal_dir))
    monkeypatch.setenv("RULES_PATH", str(rules_dir))

    from auth_rbac import AuthUser
    from decision_api.calibration_api import router as calibration_router
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
    app.include_router(calibration_router)

    async def _session_override():
        yield _EmptySession()

    app.dependency_overrides[get_session] = _session_override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client._rules_dir = rules_dir
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_promote_409_when_leftover_blocked_200_when_green(
    desk_client, tmp_path, monkeypatch
):
    from decision_api.json_rules import load_rules

    _write_shadow_pack(
        desk_client._rules_dir,
        name="scout_draft_1",
        filename="scout_draft_1.json",
        is_ai_authored=True,
    )
    load_rules()
    _patch_desk_science_green(monkeypatch)

    missing = await desk_client.post(
        "/v1/rules/shadow-packs/no_such_draft/promote",
        params={"tenant_id": "t1"},
    )
    assert missing.status_code == 404
    assert missing.json()["detail"] == "no_shadow_draft"

    _patch_leftover_fetch(monkeypatch, [{"sla_breached": True, "claimed_by": None}])
    blocked = await desk_client.post(
        "/v1/rules/shadow-packs/scout_draft_1/promote",
        params={"tenant_id": "t1"},
    )
    assert blocked.status_code == 409, blocked.text
    body = blocked.json()
    assert body["detail"] == "promote_blocked"
    assert "leftover_sla_breached" in body["leftover_promote_gate"]["blockers"]
    assert "desk_promote_gate" in body
    assert body["desk_promote_gate"]["promote_allowed"] is False
    on_disk = json.loads(
        (desk_client._rules_dir / "scout_draft_1.json").read_text(encoding="utf-8")
    )
    assert on_disk["mode"] == "shadow"

    _patch_leftover_fetch(monkeypatch, [])
    green = await desk_client.post(
        "/v1/rules/shadow-packs/scout_draft_1/promote",
        params={"tenant_id": "t1"},
    )
    assert green.status_code == 200, green.text
    out = green.json()
    assert out["promoted"] is True
    assert out["draft_id"] == "scout_draft_1"
    assert out["mode"] == "active"
    on_disk = json.loads(
        (desk_client._rules_dir / "scout_draft_1.json").read_text(encoding="utf-8")
    )
    assert on_disk["mode"] == "active"


@pytest.mark.asyncio
async def test_tick_noop_without_provision(desk_client, tmp_path, monkeypatch):
    _patch_leftover_fetch(monkeypatch, [])
    _patch_desk_science_green(monkeypatch)
    r = await desk_client.post(
        "/v1/rules/shadow-packs/auto-promote-tick",
        params={"tenant_id": "t1"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["auto_promote"] is False
    assert body["promoted"] == []
    assert body["reason"] == "not_provisioned"


@pytest.mark.asyncio
async def test_tick_promotes_ai_shadow_when_provisioned_and_green(
    desk_client, tmp_path, monkeypatch
):
    from decision_api.json_rules import load_rules
    from decision_api.shadow_auto_promote import save_provision

    _write_shadow_pack(
        desk_client._rules_dir,
        name="scout_ai",
        filename="scout_ai.json",
        is_ai_authored=True,
    )
    _write_shadow_pack(
        desk_client._rules_dir,
        name="human_canary",
        filename="human_canary.json",
        is_ai_authored=False,
    )
    load_rules()
    save_provision(
        "t1",
        auto_promote=True,
        leftover_add_cap=10,
        leftover_fp_rate_cap=0.4,
        min_labeled_extras=5,
        provisioned_by="ops",
    )
    _patch_leftover_fetch(monkeypatch, [])
    _patch_desk_science_green(monkeypatch)

    r = await desk_client.post(
        "/v1/rules/shadow-packs/auto-promote-tick",
        params={"tenant_id": "t1"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["auto_promote"] is True
    assert "scout_ai" in body["promoted"]
    assert "human_canary" not in body["promoted"]
    assert (
        json.loads((desk_client._rules_dir / "scout_ai.json").read_text(encoding="utf-8"))[
            "mode"
        ]
        == "active"
    )
    assert (
        json.loads(
            (desk_client._rules_dir / "human_canary.json").read_text(encoding="utf-8")
        )["mode"]
        == "shadow"
    )


@pytest.mark.asyncio
async def test_set_mode_active_409_on_sla(desk_client, tmp_path, monkeypatch):
    from decision_api.config import settings
    from decision_api.json_rules import load_rules
    from decision_api.rule_api import settings as rule_settings

    _write_shadow_pack(
        desk_client._rules_dir,
        name="sla_pack",
        filename="sla_pack.json",
        is_ai_authored=True,
    )
    load_rules()
    monkeypatch.setattr(settings, "rule_governance_secret", "gov-secret")
    monkeypatch.setattr(rule_settings, "rule_governance_secret", "gov-secret")
    _patch_leftover_fetch(monkeypatch, [{"sla_breached": True, "claimed_by": None}])

    r = await desk_client.put(
        "/v1/rules/sla_pack.json/mode",
        params={"tenant_id": "t1"},
        json={"mode": "active"},
        headers={"X-Rule-Governance-Secret": "gov-secret"},
    )
    assert r.status_code == 409, r.text
    body = r.json()
    leftover = body.get("leftover_promote_gate") or {}
    if not leftover and isinstance(body.get("detail"), dict):
        leftover = body["detail"].get("leftover_promote_gate") or {}
    assert "leftover_sla_breached" in leftover.get("blockers", [])
    on_disk = json.loads(
        (desk_client._rules_dir / "sla_pack.json").read_text(encoding="utf-8")
    )
    assert on_disk["mode"] == "shadow"


def _provision_auto_on(tenant_id: str = "t1") -> None:
    from decision_api.shadow_auto_promote import save_provision

    save_provision(
        tenant_id,
        auto_promote=True,
        leftover_add_cap=10,
        leftover_fp_rate_cap=0.4,
        min_labeled_extras=5,
        provisioned_by="ops",
    )


@pytest.mark.asyncio
async def test_create_scout_pack_auto_promotes_when_provisioned_and_green(
    desk_client, tmp_path, monkeypatch
):
    from decision_api.json_rules import get_shadow_packs, load_rules

    _provision_auto_on("t1")
    _patch_leftover_fetch(monkeypatch, [])
    _patch_desk_science_green(monkeypatch)

    r = await desk_client.post(
        "/v1/rules/scout-pack",
        json={
            "name": "scout_auto_tick",
            "mode": "shadow",
            "tenant_id": "t1",
            "rules": [
                {
                    "id": "r_scout",
                    "when": [{"field": "amount", "op": "gt", "value": 0}],
                    "score_delta": 10.0,
                }
            ],
            "authored_by": "scout_coordinated_burst",
            "is_ai_authored": True,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["mode"] == "shadow"
    on_disk = json.loads(
        (desk_client._rules_dir / body["file"]).read_text(encoding="utf-8")
    )
    assert on_disk["mode"] == "active"
    load_rules()
    assert get_shadow_packs() == []


@pytest.mark.asyncio
async def test_get_shadow_promote_gate_does_not_change_pack_mode(
    desk_client, tmp_path, monkeypatch
):
    from decision_api.json_rules import get_shadow_packs, load_rules

    _write_shadow_pack(
        desk_client._rules_dir,
        name="gate_no_tick",
        filename="gate_no_tick.json",
        is_ai_authored=True,
    )
    load_rules()
    _provision_auto_on("t1")
    _patch_leftover_fetch(monkeypatch, [])
    _patch_desk_science_green(monkeypatch)

    r = await desk_client.get(
        "/v1/calibration/shadow-promote-gate",
        params={"tenant_id": "t1"},
    )
    assert r.status_code == 200, r.text
    on_disk = json.loads(
        (desk_client._rules_dir / "gate_no_tick.json").read_text(encoding="utf-8")
    )
    assert on_disk["mode"] == "shadow"
    assert any(p.get("name") == "gate_no_tick" for p in get_shadow_packs())
