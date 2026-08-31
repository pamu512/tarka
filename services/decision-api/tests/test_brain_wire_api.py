"""Brain-wire API: GET no-write, tick kill, scout-pack refuse, disabled drafts."""

from __future__ import annotations

import json
from pathlib import Path

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


def _write_pack(rules_dir: Path, filename: str, **pack) -> Path:
    body = {
        "version": 1,
        "name": pack.get("name", "ai_draft"),
        "mode": pack.get("mode", "shadow"),
        "is_ai_authored": pack.get("is_ai_authored", True),
        "authored_by": pack.get("authored_by", "scout_coordinated_burst"),
        "scout_report_id": pack.get("scout_report_id", "rpt-k1"),
        "rules": pack.get(
            "rules",
            [
                {
                    "id": "scout_canvas_hash_abc123",
                    "when": [{"op": "eq", "field": "canvas_hash", "value": "abc123"}],
                    "score_delta": 25.0,
                }
            ],
        ),
    }
    if "evidence" in pack:
        body["evidence"] = pack["evidence"]
    path = rules_dir / filename
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    return path


def _fp_over_cap_gates() -> dict:
    helpfulness = {
        "blockers": ["leftover_extras_fp_over_cap"],
        "underpowered": False,
        "labeled_extras": 5,
        "extra_tp": 0,
        "extra_fp": 5,
        "fp_rate_cap": 0.4,
    }
    leftover = {
        "schema_id": "tarka.leftover_promote_gate/v1",
        "promote_allowed": False,
        "blockers": ["leftover_extras_fp_over_cap"],
        "helpfulness": helpfulness,
    }
    return {
        "leftover_promote_gate": leftover,
        "desk_promote_gate": {
            "promote_allowed": False,
            "blockers": ["leftover_promote_gate"],
        },
        "label_gated_promote": {"promote_allowed": False, "blockers": []},
        "mcnemar_promote_gate": {"promote_allowed": False, "blockers": []},
        "drift_promote_gate": {"promote_allowed": False, "blockers": []},
        "champion_challenger": {
            "schema_id": "tarka.champion_challenger_audit/v1",
            "audit_rows": [],
        },
        "labeled_champion_challenger_f1": {},
        "label_posture": {},
        "live_rule_slip": {"window": "ok", "rules": []},
        "rule_precision_after_labels": {
            "schema_id": "tarka.rule_precision_after_labels/v1",
            "rules": [],
        },
    }


def _underpowered_gates() -> dict:
    g = _fp_over_cap_gates()
    helpfulness = {
        "blockers": [],
        "underpowered": True,
        "labeled_extras": 3,
        "extra_tp": 1,
        "extra_fp": 2,
        "fp_rate_cap": 0.4,
    }
    g["leftover_promote_gate"] = {
        "schema_id": "tarka.leftover_promote_gate/v1",
        "promote_allowed": False,
        "blockers": ["leftover_sla_breached"],
        "helpfulness": helpfulness,
        "hint": "helpfulness_underpowered",
    }
    return g


def _scout_body(**extra) -> dict:
    body = {
        "name": "Scout: canvas_hash abc123",
        "mode": "shadow",
        "rules": [
            {
                "id": "scout_canvas_hash_abc123",
                "when": [{"op": "eq", "field": "canvas_hash", "value": "abc123"}],
                "score_delta": 25.0,
            }
        ],
        "authored_by": "scout_coordinated_burst",
        "is_ai_authored": True,
        "scout_report_id": "rpt-001",
        "tenant_id": "t1",
    }
    body.update(extra)
    return body


@pytest.fixture
async def api_client(tmp_path, monkeypatch):
    rules_dir = tmp_path / "rules"
    cal_dir = tmp_path / "cal"
    rules_dir.mkdir()
    cal_dir.mkdir()
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    monkeypatch.setenv("CALIBRATION_DATA_DIR", str(cal_dir))
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///")
    monkeypatch.delenv("RULE_GOVERNANCE_SECRET", raising=False)

    from auth_rbac import AuthUser
    from decision_api.calibration_api import router as calibration_router
    from decision_api.config import settings
    from decision_api.rule_api import router as rules_router

    monkeypatch.setattr(settings, "rules_path", str(rules_dir))
    monkeypatch.setattr(settings, "rule_governance_secret", "")

    async def _no_park(tenant_id, **_k):
        return {"parked": [], "skipped": []}

    monkeypatch.setattr(
        "decision_api.live_rule_slip.maybe_park_live_rule_slip", _no_park
    )
    monkeypatch.setattr(
        "decision_api.rule_api.maybe_park_live_rule_slip", _no_park
    )

    class _CM:
        async def __aenter__(self):
            return _EmptySession()

        async def __aexit__(self, *a):
            return None

    monkeypatch.setattr("decision_api.db.SessionLocal", lambda: _CM())

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


def _patch_leftover_compute(monkeypatch, gates: dict):
    async def _compute(tid, draft_id, session=None):
        return gates

    monkeypatch.setattr(
        "decision_api.leftover_promote_gate.compute_desk_and_leftover_gates",
        _compute,
    )


@pytest.mark.asyncio
async def test_get_shadow_promote_gate_never_disables_file(api_client, monkeypatch):
    from decision_api.json_rules import load_rules

    _write_pack(api_client._rules_dir, "ai.json")
    load_rules()
    before = {p.name: p.read_text(encoding="utf-8") for p in api_client._rules_dir.glob("*.json")}
    _patch_leftover_compute(monkeypatch, _fp_over_cap_gates())

    r = await api_client.get(
        "/v1/calibration/shadow-promote-gate", params={"tenant_id": "t1"}
    )
    assert r.status_code == 200, r.text
    after = {p.name: p.read_text(encoding="utf-8") for p in api_client._rules_dir.glob("*.json")}
    assert after == before
    assert json.loads((api_client._rules_dir / "ai.json").read_text(encoding="utf-8"))["mode"] == "shadow"


@pytest.mark.asyncio
async def test_get_shadow_drafts_includes_disabled_ai_pack(api_client):
    from decision_api.json_rules import load_rules

    _write_pack(api_client._rules_dir, "dead.json", name="killed_draft", mode="disabled")
    load_rules()

    r = await api_client.get(
        "/v1/calibration/shadow-promote-gate", params={"tenant_id": "t1"}
    )
    assert r.status_code == 200, r.text
    drafts = r.json()["shadow_drafts"]
    dead = next(d for d in drafts if d["name"] == "killed_draft")
    assert dead["is_ai_authored"] is True
    assert dead["mode"] == "disabled"


@pytest.mark.asyncio
async def test_tick_fp_over_cap_disables_ai_shadow(api_client, monkeypatch):
    from decision_api.json_rules import load_rules

    _write_pack(api_client._rules_dir, "ai.json", name="ai_draft")
    load_rules()
    _patch_leftover_compute(monkeypatch, _fp_over_cap_gates())

    r = await api_client.post(
        "/v1/rules/shadow-packs/auto-promote-tick", params={"tenant_id": "t1"}
    )
    assert r.status_code == 200, r.text
    on_disk = json.loads((api_client._rules_dir / "ai.json").read_text(encoding="utf-8"))
    assert on_disk["mode"] == "disabled"


@pytest.mark.asyncio
async def test_promote_disabled_pack_is_404(api_client):
    from decision_api.json_rules import load_rules

    _write_pack(api_client._rules_dir, "dead.json", name="killed_draft", mode="disabled")
    load_rules()

    r = await api_client.post(
        "/v1/rules/shadow-packs/killed_draft/promote", params={"tenant_id": "t1"}
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "no_shadow_draft"


@pytest.mark.asyncio
async def test_scout_pack_no_tenant_409(api_client):
    r = await api_client.post(
        "/v1/rules/scout-pack",
        json=_scout_body(tenant_id=""),
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "leftover_helpfulness_no_tenant"
    assert list(api_client._rules_dir.glob("scout_*.json")) == []


@pytest.mark.asyncio
async def test_scout_pack_killed_fingerprint_409(api_client, tmp_path, monkeypatch):
    from decision_api.brain_wire import add_killed_fingerprints

    add_killed_fingerprints("t1", [("scout_report_id", "rpt-dead")])
    r = await api_client.post(
        "/v1/rules/scout-pack",
        json=_scout_body(scout_report_id="rpt-dead"),
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "leftover_helpfulness_killed"
    assert list(api_client._rules_dir.glob("scout_*.json")) == []


@pytest.mark.asyncio
async def test_scout_pack_leftover_drop_409(api_client, monkeypatch):
    _patch_leftover_compute(monkeypatch, _fp_over_cap_gates())
    r = await api_client.post("/v1/rules/scout-pack", json=_scout_body())
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "leftover_extras_fp_over_cap"
    assert list(api_client._rules_dir.glob("scout_*.json")) == []


@pytest.mark.asyncio
async def test_scout_pack_underpowered_stamps_evidence_stays_shadow(
    api_client, monkeypatch
):
    _patch_leftover_compute(monkeypatch, _underpowered_gates())
    r = await api_client.post("/v1/rules/scout-pack", json=_scout_body())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["mode"] == "shadow"
    ev = body["pack"]["evidence"]["leftover_helpfulness"]
    assert ev["hint"] == "helpfulness_underpowered"
    assert ev["labeled_extras"] == 3
    assert ev["extra_tp"] == 1
    assert ev["extra_fp"] == 2
    filename = body["file"]
    on_disk = json.loads((api_client._rules_dir / filename).read_text(encoding="utf-8"))
    assert on_disk["mode"] == "shadow"
    assert on_disk["evidence"]["leftover_helpfulness"]["hint"] == "helpfulness_underpowered"


def test_tick_sites_call_kill_get_does_not():
    cal = Path("src/decision_api/calibration_api.py").read_text(encoding="utf-8")
    rules = Path("src/decision_api/rule_api.py").read_text(encoding="utf-8")
    tick = cal.split("async def _tick_auto_promote")[1].split("\ndef ")[0]
    assert "maybe_kill_leftover_fp_shadows" in tick
    get_fn = cal.split("async def shadow_promote_gate")[1].split("async def ")[0]
    assert "maybe_kill" not in get_fn
    assert "maybe_kill_leftover_fp_shadows" in rules.split("async def auto_promote_tick")[1].split(
        "async def "
    )[0]
    assert "maybe_kill_leftover_fp_shadows" in rules.split("async def create_scout_pack")[1].split(
        "async def "
    )[0]


class _DummyAudit:
    decision = "deny"
    score = 80.0
    payload_snapshot = {"payload": {"amount": 100}, "metadata": {}}
    rule_hits = []


class _RecordsSession:
    async def execute(self, *a, **k):
        class _R:
            def scalars(self):
                return self

            def all(self):
                return [_DummyAudit() for _ in range(20)]

        return _R()


@pytest.mark.asyncio
async def test_analyze_rule_fp_over_cap_goes_to_dropped(monkeypatch):
    from decision_api.recommend_api import router as recommend_router
    from decision_api.rule_recommender import RuleRecommendation

    rec = RuleRecommendation(
        rule_id="r1",
        description="high-fp candidate",
        conditions=[{"field": "amount", "op": "gt", "value": 50}],
        suggested_score_delta=10.0,
        confidence=0.8,
        support=20,
        precision=0.2,
        recall=0.1,
        lift=1.2,
    )
    monkeypatch.setattr(
        "decision_api.recommend_api.generate_recommendations",
        lambda *a, **k: [rec],
    )
    gates = _fp_over_cap_gates()
    gates["leftover_promote_gate"]["helpfulness"] = {
        "blockers": [],
        "underpowered": False,
        "labeled_extras": 5,
        "extra_tp": 3,
        "extra_fp": 2,
        "fp_rate_cap": 0.4,
    }
    gates["leftover_promote_gate"]["blockers"] = []
    gates["rule_precision_after_labels"] = {
        "schema_id": "tarka.rule_precision_after_labels/v1",
        "rules": [{"rule_id": "r1", "enough_support": True, "fp_rate": 0.8}],
    }
    _patch_leftover_compute(monkeypatch, gates)

    app = FastAPI()
    app.include_router(recommend_router)

    async def _session_override():
        yield _RecordsSession()

    app.dependency_overrides[get_session] = _session_override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/v1/recommendations/analyze",
            json={"tenant_id": "t1"},
        )
    app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    body = r.json()
    rec_ids = [x.get("rule_id") for x in body.get("recommendations") or []]
    assert "r1" not in rec_ids
    assert {"rule_id": "r1", "reason": "rule_fp_over_cap"} in body.get("dropped", [])
