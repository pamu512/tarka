"""A1 L2: leftover/override → Observe shadow draft + backtest gate."""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from decision_api.l2_draft import (
    L2DraftError,
    abandon_draft,
    authored_by_kind,
    build_l2_draft,
    find_open_draft,
    mark_promoted,
)
from decision_api.rule_pack_validation import validate_rule_pack


def _receipt(*, tenant_id="acme", entity_id="ent-1", trace_id=None):
    return SimpleNamespace(
        tenant_id=tenant_id,
        entity_id=entity_id,
        trace_id=trace_id or uuid4(),
        event_type="login",
        rule_hits=["hit_a"],
    )


def test_empty_llm_is_deterministic_never_ai_suggested():
    pack = build_l2_draft(
        receipt=_receipt(),
        leftover_id="lo-1",
        authored_by="vertex",
        is_ai_authored=True,
        llm_url="",
        skip_backtest=True,
        backtest_ok=False,
        actor="ana-1",
        skip_reason="deterministic leftover seed",
    )
    assert pack["mode"] == "shadow"
    assert pack["authored_by"] in {"human", "seed", ""}
    assert pack["is_ai_authored"] is False
    assert "AI-suggested" not in json.dumps(pack)
    assert pack["tenant_id"] == "acme"
    assert pack["tenant_id"] != "demo"
    assert validate_rule_pack(pack) == []


def test_human_may_skip_backtest_into_observe():
    pack = build_l2_draft(
        receipt=_receipt(),
        leftover_id="lo-1",
        authored_by="human",
        is_ai_authored=False,
        llm_url="",
        skip_backtest=True,
        backtest_ok=False,
        actor="ana-1",
        skip_reason="seasonal known good",
    )
    assert pack["mode"] == "shadow"
    assert pack["authored_by"] == "human"
    assert pack["lifecycle"]["state"] == "observe"
    assert pack["lifecycle"]["gate"] == "backtest_skipped_human"
    skip = pack["lifecycle"]["skip"]
    assert skip["actor"] == "ana-1"
    assert skip["reason"] == "seasonal known good"
    assert skip["at"]


def test_human_skip_requires_actor_and_reason():
    with pytest.raises(L2DraftError) as ei:
        build_l2_draft(
            receipt=_receipt(),
            leftover_id="lo-1",
            authored_by="human",
            skip_backtest=True,
            actor="",
            skip_reason="",
        )
    assert ei.value.code == "skip_audit_required"
    assert ei.value.http_status == 400


def test_lifecycle_hash_and_schema_on_observe_pack():
    pack = build_l2_draft(
        receipt=_receipt(),
        leftover_id="lo-1",
        authored_by="human",
        skip_backtest=True,
        actor="ana-1",
        skip_reason="ok",
    )
    assert pack["schema_version"] == 1
    assert pack["source_key"] == "leftover:lo-1"
    assert pack["pack_hash"]
    assert len(pack["pack_hash"]) == 64
    assert pack["lifecycle"]["state"] == "observe"
    assert pack["lifecycle"]["created_at"]
    assert pack["lifecycle"]["observe_entered_at"]


def test_abandon_and_promote_close_open_draft():
    pack = build_l2_draft(
        receipt=_receipt(),
        leftover_id="lo-1",
        authored_by="human",
        skip_backtest=True,
        actor="ana-1",
        skip_reason="ok",
    )
    abandoned = abandon_draft(pack, actor="ana-1")
    assert abandoned["lifecycle"]["state"] == "abandoned"
    assert abandoned["lifecycle"]["abandoned_by"] == "ana-1"
    assert find_open_draft([abandoned], leftover_id="lo-1") is None
    again = build_l2_draft(
        receipt=_receipt(),
        leftover_id="lo-1",
        authored_by="human",
        skip_backtest=True,
        actor="ana-1",
        skip_reason="retry",
    )
    promoted = mark_promoted(again)
    assert promoted["lifecycle"]["state"] == "promoted"
    assert promoted["lifecycle"]["promoted_at"]
    assert find_open_draft([promoted], leftover_id="lo-1") is None


def test_ai_observe_records_backtest_pass_artifact():
    pack = build_l2_draft(
        receipt=_receipt(),
        leftover_id="lo-1",
        authored_by="scout",
        is_ai_authored=True,
        llm_url="http://llm.example",
        skip_backtest=False,
        backtest_ok=True,
        backtest_artifact_id="replay-9",
        rules=[
            {
                "id": "r1",
                "when": [{"field": "entity_id", "op": "eq", "value": "ent-1"}],
                "score_delta": 5,
            }
        ],
    )
    assert pack["lifecycle"]["state"] == "observe"
    assert pack["lifecycle"]["gate"] == "backtest_passed"
    assert pack["lifecycle"]["backtest_artifact_id"] == "replay-9"
    assert pack["lifecycle"]["skip"] is None


def test_idempotent_open_draft_conflicts():
    from decision_api.l2_draft import find_open_draft

    existing = [
        {
            "name": "l2_lo-1",
            "source_key": "leftover:lo-1",
            "lifecycle": {"state": "observe"},
            "_file": "l2_aaa.json",
        }
    ]
    hit = find_open_draft(existing, leftover_id="lo-1", hil_event_id="")
    assert hit["_file"] == "l2_aaa.json"
    assert (
        find_open_draft(
            [{**existing[0], "lifecycle": {"state": "abandoned"}}],
            leftover_id="lo-1",
            hil_event_id="",
        )
        is None
    )


def test_ai_blocked_without_backtest_pass():
    with pytest.raises(L2DraftError) as ei:
        build_l2_draft(
            receipt=_receipt(),
            leftover_id="lo-1",
            authored_by="scout",
            is_ai_authored=True,
            llm_url="http://llm.example",
            skip_backtest=True,
            backtest_ok=False,
        )
    assert ei.value.code == "backtest_required"
    assert ei.value.http_status == 409


def test_ai_enters_observe_after_backtest_pass():
    pack = build_l2_draft(
        receipt=_receipt(),
        leftover_id="lo-1",
        override_why="seasonal spike",
        authored_by="scout",
        is_ai_authored=True,
        llm_url="http://llm.example",
        skip_backtest=False,
        backtest_ok=True,
        rules=[
            {
                "id": "r1",
                "when": [{"field": "entity_id", "op": "eq", "value": "ent-1"}],
                "score_delta": 5,
            }
        ],
    )
    assert pack["mode"] == "shadow"
    assert pack["is_ai_authored"] is True
    assert pack["evidence"]["override_why"] == "seasonal spike"


def test_invalid_schema_is_dropped():
    with pytest.raises(L2DraftError) as ei:
        build_l2_draft(
            receipt=_receipt(),
            leftover_id="lo-1",
            authored_by="human",
            is_ai_authored=False,
            llm_url="",
            skip_backtest=True,
            backtest_ok=False,
            actor="ana-1",
            skip_reason="schema probe",
            rules=[{"id": "bad", "when": [], "score_delta": 5}],
        )
    assert ei.value.code == "schema_invalid"
    assert ei.value.http_status == 422


def test_live_evaluate_never_sees_draft(tmp_path, monkeypatch):
    from decision_api import json_rules
    from decision_api.config import settings

    monkeypatch.setattr(settings, "rules_path", str(tmp_path))
    pack = build_l2_draft(
        receipt=_receipt(),
        leftover_id="lo-1",
        authored_by="human",
        is_ai_authored=False,
        llm_url="",
        skip_backtest=True,
        backtest_ok=False,
        actor="ana-1",
        skip_reason="isolation check",
    )
    (tmp_path / "l2.json").write_text(json.dumps(pack), encoding="utf-8")
    json_rules.load_rules()
    names = {p.get("name") for p in json_rules.get_shadow_packs()}
    active = {p.get("name") for p in json_rules.get_active_packs_snapshot()}
    assert pack["name"] in names
    assert pack["name"] not in active


def test_authored_by_kind_never_ai_theater_when_llm_empty():
    kind, ai = authored_by_kind("Vertex", is_ai_authored=True, llm_url="")
    assert ai is False
    assert kind in {"human", "seed", ""}


def test_l2_module_does_not_promote_or_decide():
    import decision_api.l2_draft as mod

    src = open(mod.__file__, encoding="utf-8").read()
    assert "activate_shadow_pack" not in src
    assert "force_live" not in src
    assert "ALLOW" not in src
    assert "DENY" not in src
    assert "Promote" not in src


class _AuditRow:
    def __init__(self, tid):
        self.tenant_id = "acme"
        self.entity_id = "ent-1"
        self.trace_id = tid
        self.event_type = "login"
        self.decision = "review"
        self.score = 55.0
        self.rule_hits = ["hit_a"]
        self.payload_snapshot = {"payload": {"entity_id": "ent-1"}, "metadata": {}}
        self.created_at = None


class _AuditSession:
    def __init__(self, row):
        self.row = row

    async def execute(self, *a, **k):
        row = self.row

        class _R:
            def scalars(self):
                return self

            def first(self):
                return row

            def all(self):
                return [row]

        return _R()


@pytest.fixture
async def l2_client(tmp_path, monkeypatch):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    tid = uuid4()
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("SHADOW_LLM_BASE_URL", raising=False)

    from auth_rbac import AuthUser
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from decision_api.config import settings
    from decision_api.db import get_session
    from decision_api.observe_drafts import router as observe_router
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
    app.include_router(observe_router)

    async def _session_override():
        yield _AuditSession(_AuditRow(tid))

    app.dependency_overrides[get_session] = _session_override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c._rules_dir = rules_dir
        c._trace_id = str(tid)
        yield c
    app.dependency_overrides.clear()


def _human_body(trace_id: str) -> dict:
    return {
        "leftover_id": "lo-1",
        "trace_id": trace_id,
        "override_why": "known good",
        "authored_by": "human",
        "skip_backtest": True,
        "skip_reason": "seasonal known good",
    }


@pytest.mark.asyncio
async def test_http_human_skip_lands_in_observe(l2_client):
    r = await l2_client.post(
        "/v1/rules/l2-draft",
        json=_human_body(l2_client._trace_id),
        headers={"X-Actor": "ana-1"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["pack"]["mode"] == "shadow"
    assert body["pack"]["lifecycle"]["state"] == "observe"
    assert body["pack"]["lifecycle"]["gate"] == "backtest_skipped_human"
    listed = await l2_client.get("/v1/rules/l2-drafts")
    assert listed.status_code == 200
    names = {p["name"] for p in listed.json()["items"]}
    assert body["pack"]["name"] in names


@pytest.mark.asyncio
async def test_http_ai_skip_is_409(l2_client, monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "http://llm.example")
    r = await l2_client.post(
        "/v1/rules/l2-draft",
        json={
            "leftover_id": "lo-1",
            "trace_id": l2_client._trace_id,
            "authored_by": "scout",
            "is_ai_authored": True,
            "skip_backtest": True,
        },
        headers={"X-Actor": "ana-1"},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "backtest_required"


@pytest.mark.asyncio
async def test_http_duplicate_open_draft_is_409(l2_client):
    first = await l2_client.post(
        "/v1/rules/l2-draft",
        json=_human_body(l2_client._trace_id),
        headers={"X-Actor": "ana-1"},
    )
    assert first.status_code == 201, first.text
    second = await l2_client.post(
        "/v1/rules/l2-draft",
        json=_human_body(l2_client._trace_id),
        headers={"X-Actor": "ana-1"},
    )
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "draft_exists"


@pytest.mark.asyncio
async def test_http_abandon_closes_draft(l2_client):
    created = await l2_client.post(
        "/v1/rules/l2-draft",
        json=_human_body(l2_client._trace_id),
        headers={"X-Actor": "ana-1"},
    )
    assert created.status_code == 201, created.text
    name = created.json()["pack"]["name"]
    gone = await l2_client.post(
        f"/v1/rules/l2-drafts/{name}/abandon",
        headers={"X-Actor": "ana-1"},
    )
    assert gone.status_code == 200, gone.text
    assert gone.json()["pack"]["lifecycle"]["state"] == "abandoned"
    listed = await l2_client.get("/v1/observe/drafts?state=abandoned")
    assert listed.status_code == 200
    names = {p["name"] for p in listed.json()["items"]}
    assert name in names
