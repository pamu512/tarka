"""Observe notify store + webhook (desk + optional outbound)."""

from __future__ import annotations

import json

import pytest

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from decision_api.observe_notify import (
    EVENT_CONSIDER_DEMOTE,
    EVENT_CONSIDER_SUCCESSOR,
    EVENT_LIVE_RULE_SLIPPED,
    EVENT_READY_TO_PROMOTE,
    NOTIFY_SCHEMA,
    byom_status,
    emit_observe_event,
    english_copy,
    list_notify,
    mark_read,
    maybe_emit_promote_ready,
    maybe_emit_slip_events,
)


def test_evaluate_pipeline_does_not_emit_notify() -> None:
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "decision_api"
    outcome = (src / "decision_outcome.py").read_text(encoding="utf-8")
    assert "observe_notify" not in outcome
    main = (src / "main.py").read_text(encoding="utf-8")
    ev = main.split("async def evaluate_decision")[1].split("async def ")[0]
    assert "observe_notify" not in ev
    assert "emit_observe_event" not in ev
    cal = (src / "calibration_api.py").read_text(encoding="utf-8")
    get_fn = cal.split("async def shadow_promote_gate")[1].split("async def ")[0]
    assert "emit_after_observe_tick" not in get_fn
    assert "emit_observe_event" not in get_fn


def test_english_copy_has_no_third_party_desk_names() -> None:
    blob = " ".join(
        " ".join(english_copy(kind, "sdk_bot", "draft_a").values())
        for kind in (
            EVENT_READY_TO_PROMOTE,
            EVENT_LIVE_RULE_SLIPPED,
            EVENT_CONSIDER_DEMOTE,
            EVENT_CONSIDER_SUCCESSOR,
        )
    )
    assert "unit21" not in blob.lower()
    assert "sardine" not in blob.lower()
    assert "Promote" in blob or "Observe" in blob


def test_dedupe_same_tenant_type_subject(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TARKA_OBSERVE_NOTIFY_PATH", str(tmp_path / "notify.jsonl"))
    monkeypatch.delenv("TARKA_OBSERVE_NOTIFY_WEBHOOK_URL", raising=False)
    first = emit_observe_event(
        tenant_id="demo",
        event_type=EVENT_READY_TO_PROMOTE,
        subject_id="pack_a",
    )
    second = emit_observe_event(
        tenant_id="demo",
        event_type=EVENT_READY_TO_PROMOTE,
        subject_id="pack_a",
    )
    assert first["created"] is True
    assert second["created"] is False
    rows = list_notify("demo")
    assert len(rows) == 1
    assert rows[0]["type"] == EVENT_READY_TO_PROMOTE
    assert rows[0]["href"].startswith("/ops/shadow")


def test_empty_webhook_url_does_not_post(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TARKA_OBSERVE_NOTIFY_PATH", str(tmp_path / "notify.jsonl"))
    monkeypatch.delenv("TARKA_OBSERVE_NOTIFY_WEBHOOK_URL", raising=False)
    posts: list[object] = []

    class _Http:
        def post(self, *_a, **_k):
            posts.append(1)
            raise AssertionError("webhook must not fire when URL unset")

    out = emit_observe_event(
        tenant_id="demo",
        event_type=EVENT_LIVE_RULE_SLIPPED,
        subject_id="r1",
        http=_Http(),
    )
    assert out["webhook"] == "skipped"
    assert posts == []


def test_webhook_posts_versioned_envelope(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TARKA_OBSERVE_NOTIFY_PATH", str(tmp_path / "notify.jsonl"))
    monkeypatch.setenv("TARKA_OBSERVE_NOTIFY_WEBHOOK_URL", "http://hooks.test/obs")
    monkeypatch.setenv("TARKA_OBSERVE_NOTIFY_WEBHOOK_SECRET", "sekrit")
    posts: list[dict] = []

    class _Resp:
        status_code = 204

    class _Http:
        def post(self, url, content=None, headers=None, timeout=None):
            posts.append(
                {"url": url, "content": content, "headers": dict(headers or {})}
            )
            return _Resp()

    out = emit_observe_event(
        tenant_id="acme",
        event_type=EVENT_CONSIDER_DEMOTE,
        subject_id="live_rule",
        http=_Http(),
    )
    assert out["created"] is True
    assert out["webhook"] == "acked"
    assert len(posts) == 1
    body = json.loads(posts[0]["content"])
    assert body["schema_id"] == NOTIFY_SCHEMA
    assert body["event"] == EVENT_CONSIDER_DEMOTE
    assert body["tenant_id"] == "acme"
    assert "x-tarka-signature" in posts[0]["headers"]
    assert posts[0]["headers"]["x-tarka-observe-notify-event"] == EVENT_CONSIDER_DEMOTE


def test_promote_ready_only_when_gates_pass(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TARKA_OBSERVE_NOTIFY_PATH", str(tmp_path / "notify.jsonl"))
    monkeypatch.delenv("TARKA_OBSERVE_NOTIFY_WEBHOOK_URL", raising=False)
    blocked = maybe_emit_promote_ready(
        "demo",
        desk={"promote_allowed": False, "blockers": ["labels"]},
        drafts=[{"name": "scout_a"}],
    )
    assert blocked == []
    assert list_notify("demo") == []
    created = maybe_emit_promote_ready(
        "demo",
        desk={"promote_allowed": True, "blockers": []},
        drafts=[{"name": "scout_a"}],
    )
    assert [r["subject_id"] for r in created] == ["scout_a"]


def test_slip_ping_vs_park_kinds(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TARKA_OBSERVE_NOTIFY_PATH", str(tmp_path / "notify.jsonl"))
    monkeypatch.delenv("TARKA_OBSERVE_NOTIFY_WEBHOOK_URL", raising=False)
    maybe_emit_slip_events(
        "demo",
        slip={
            "rules": [
                {"rule_id": "noisy", "hypothesis": "retire"},
                {"rule_id": "changed", "hypothesis": "successor"},
                {"rule_id": "thin", "hypothesis": "underpowered"},
            ]
        },
        parked=["slip_retire_noisy", "slip_successor_changed"],
    )
    types = {r["subject_id"]: r["type"] for r in list_notify("demo")}
    assert types["noisy"] == EVENT_CONSIDER_DEMOTE
    assert types["changed"] == EVENT_CONSIDER_SUCCESSOR
    assert types["thin"] == EVENT_LIVE_RULE_SLIPPED


def test_mark_read(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TARKA_OBSERVE_NOTIFY_PATH", str(tmp_path / "notify.jsonl"))
    monkeypatch.delenv("TARKA_OBSERVE_NOTIFY_WEBHOOK_URL", raising=False)
    emit_observe_event(
        tenant_id="demo",
        event_type=EVENT_READY_TO_PROMOTE,
        subject_id="p1",
    )
    row = list_notify("demo")[0]
    assert row["read_at"] is None
    assert mark_read("demo", row["id"])["read_at"]
    assert list_notify("demo")[0]["read_at"]


def test_byom_status_never_echoes_key(monkeypatch) -> None:
    monkeypatch.delenv("SHADOW_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("SHADOW_LLM_API_KEY", raising=False)
    off = byom_status()
    assert off["connected"] is False
    assert off["backend"] == "off"
    assert "api_key" not in off
    monkeypatch.setenv("SHADOW_LLM_BASE_URL", "http://user:pw@llm.test/v1")
    monkeypatch.setenv("SHADOW_LLM_API_KEY", "sk-secret")
    monkeypatch.setenv("SHADOW_LLM_BACKEND", "vllm")
    monkeypatch.setenv("SHADOW_LLM_MODEL", "llama")
    on = byom_status()
    assert on["connected"] is True
    assert on["backend"] == "vllm"
    assert on["model"] == "llama"
    assert "sk-secret" not in json.dumps(on)
    assert "pw" not in json.dumps(on)
    assert "api_key" not in on


@pytest.mark.asyncio
async def test_notify_http_list_and_read(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    monkeypatch.setenv("TARKA_OBSERVE_NOTIFY_PATH", str(tmp_path / "notify.jsonl"))
    monkeypatch.delenv("TARKA_OBSERVE_NOTIFY_WEBHOOK_URL", raising=False)
    emit_observe_event(
        tenant_id="demo",
        event_type=EVENT_READY_TO_PROMOTE,
        subject_id="pack_a",
    )
    from auth_rbac import AuthUser
    from decision_api.observe_notify import router

    app = FastAPI()

    @app.middleware("http")
    async def _inject_auth(request, call_next):
        request.state.auth_user = AuthUser(
            "test-analyst", ["analyst"], "test", tenant_ids={"*"}
        )
        return await call_next(request)

    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        listed = await client.get("/v1/observe-notify", params={"tenant_id": "demo"})
        assert listed.status_code == 200
        body = listed.json()
        assert body["unread"] == 1
        nid = body["notifications"][0]["id"]
        marked = await client.post(
            f"/v1/observe-notify/{nid}/read", params={"tenant_id": "demo"}
        )
        assert marked.status_code == 200
        again = await client.get("/v1/observe-notify", params={"tenant_id": "demo"})
        assert again.json()["unread"] == 0
        status = await client.get("/v1/ops/byom-status")
        assert status.status_code == 200
        assert status.json()["connected"] is False
