from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time

import pytest
from collaboration_chat_bridge.agent_client import AgentChatError, AgentUpstreamError
from collaboration_chat_bridge.main import app
from collaboration_chat_bridge.rate_limit import MinuteRateLimiter
from collaboration_chat_bridge.reply_format import (
    escape_slack_mrkdwn,
    format_slack_blocks,
    normalize_slack_user_text,
)
from collaboration_chat_bridge.secrets_util import constant_time_string_equals
from collaboration_chat_bridge.slack_verify import verify_slack_signature
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["service"] == "collaboration-chat-bridge"


def test_verify_slack_signature_ok():
    secret = "shh"
    ts = str(int(time.time()))
    body = b'{"type":"event_callback"}'
    basestring = f"v0:{ts}:".encode() + body
    sig = "v0=" + hmac.new(secret.encode(), basestring, hashlib.sha256).hexdigest()
    assert verify_slack_signature(secret, ts, body, sig) is True


def test_verify_slack_signature_bad():
    assert verify_slack_signature("a", "1", b"{}", "v0=deadbeef") is False


def test_constant_time_string_equals():
    assert constant_time_string_equals("secret", "secret") is True
    assert constant_time_string_equals("secret", "other") is False
    assert constant_time_string_equals("ab", "a") is False


def test_normalize_slack_user_text():
    assert normalize_slack_user_text("<@U123> hello") == "hello"
    assert normalize_slack_user_text("<https://ex.com|label>") == "https://ex.com"


def test_escape_slack_mrkdwn():
    assert "&lt;script&gt;" in escape_slack_mrkdwn("<script>")


def test_format_slack_blocks_includes_persona_context():
    agent = {"reply": "Hi", "turn_id": "t1", "persona": "orchestrator", "answer_sections": {}}
    blocks = format_slack_blocks(agent)
    joined = str(blocks)
    assert "orchestrator" in joined
    assert "t1" in joined


def test_format_slack_blocks_inferences():
    agent = {
        "reply": "Summary here",
        "turn_id": "t1",
        "answer_sections": {
            "sections_found": ["inferences", "next_steps"],
            "facts_from_tools": "- id: 1",
            "inferences": "- Likely account takeover\n- Velocity spike",
            "next_steps": "- Pull `get_decision_audit` for trace X",
        },
    }
    blocks = format_slack_blocks(agent)
    joined = str(blocks)
    assert "INFERENCES" in joined
    assert "NEXT STEPS" in joined
    assert "FACTS FROM TOOLS" in joined


@pytest.mark.asyncio
async def test_slack_url_verification(monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "shh")
    import collaboration_chat_bridge.main as m

    m.settings = m.Settings()

    ts = str(int(time.time()))
    body_dict = {"type": "url_verification", "challenge": "abc123"}
    body = json.dumps(body_dict).encode()
    basestring = f"v0:{ts}:".encode() + body
    sig = "v0=" + hmac.new(b"shh", basestring, hashlib.sha256).hexdigest()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/v1/slack/events",
            content=body,
            headers={"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig},
        )
    assert r.status_code == 200
    assert r.json().get("challenge") == "abc123"
    assert isinstance(r.headers.get("x-correlation-id"), str) and r.headers.get("x-correlation-id")


@pytest.mark.asyncio
async def test_slack_event_forwards_correlation_to_background_turn(monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "shh")
    seen: dict[str, object] = {}

    async def fake_process(_settings, _raw_body):
        return {
            "_async_slack": True,
            "channel": "C123",
            "user": "U123",
            "text": "hello",
            "thread_ts": "1.1",
            "ts": "1.1",
            "files": [],
            "team_id": "T1",
        }

    async def fake_run_slack_turn(_settings, meta):
        seen.update(meta)

    import collaboration_chat_bridge.main as m

    m.settings = m.Settings()
    monkeypatch.setattr(m, "process_slack_event_payload", fake_process)
    monkeypatch.setattr(m, "run_slack_turn", fake_run_slack_turn)

    ts = str(int(time.time()))
    body = json.dumps({"type": "event_callback", "team_id": "T1", "event": {"type": "app_mention"}}).encode()
    basestring = f"v0:{ts}:".encode() + body
    sig = "v0=" + hmac.new(b"shh", basestring, hashlib.sha256).hexdigest()

    transport = ASGITransport(app=m.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/v1/slack/events",
            content=body,
            headers={
                "X-Slack-Request-Timestamp": ts,
                "X-Slack-Signature": sig,
                "X-Request-Id": "req-slack-1",
            },
        )
    assert r.status_code == 200
    assert r.headers.get("x-correlation-id") == "req-slack-1"
    assert seen.get("correlation_id") == "req-slack-1"


@pytest.mark.asyncio
async def test_teams_bridge_secret(monkeypatch):
    monkeypatch.setenv("TEAMS_BRIDGE_SECRET", "tsec")
    seen: dict[str, object] = {}

    async def fake_post_chat(*_a, **_k):
        seen.update(_k)
        return {
            "reply": "Synthetic reply",
            "turn_id": "turn-test",
            "answer_sections": {"inferences": "Test inference", "next_steps": "Do X"},
        }

    import collaboration_chat_bridge.main as m

    m.settings = m.Settings()
    monkeypatch.setattr(m, "post_chat", fake_post_chat)

    transport = ASGITransport(app=m.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r_bad = await client.post("/v1/teams/messages", json={"text": "hi"})
        assert r_bad.status_code == 401
        assert isinstance(r_bad.headers.get("x-correlation-id"), str) and r_bad.headers.get("x-correlation-id")
        r_ok = await client.post(
            "/v1/teams/messages",
            json={"text": "hello", "analyst_id": "u1"},
            headers={"X-Bridge-Secret": "tsec", "X-Request-Id": "req-teams-1"},
        )
    assert r_ok.status_code == 200
    data = r_ok.json()
    assert data.get("ok") is True
    assert "adaptive_card" in data
    assert data["raw"]["turn_id"] == "turn-test"
    assert r_ok.headers.get("x-correlation-id") == "req-teams-1"
    assert seen.get("correlation_id") == "req-teams-1"


@pytest.mark.asyncio
async def test_teams_agent_error_returns_card(monkeypatch):
    monkeypatch.setenv("TEAMS_BRIDGE_SECRET", "tsec")

    async def boom(*_a, **_k):
        raise AgentChatError("upstream down", status_code=503, body_snippet="detail")

    import collaboration_chat_bridge.main as m

    m.settings = m.Settings()
    monkeypatch.setattr(m, "post_chat", boom)

    transport = ASGITransport(app=m.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/v1/teams/messages",
            json={"text": "hello"},
            headers={"X-Bridge-Secret": "tsec"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is False
    assert data.get("error") == "copilot_unavailable"
    assert data.get("agent_http_status") == 503
    assert isinstance(r.headers.get("x-correlation-id"), str) and r.headers.get("x-correlation-id")
    assert "adaptive_card" in data


@pytest.mark.asyncio
async def test_teams_ingress_audit_logs_unavailable_has_upstream_status(monkeypatch, caplog):
    monkeypatch.setenv("TEAMS_BRIDGE_SECRET", "tsec")

    async def boom(*_a, **_k):
        raise AgentChatError("upstream down", status_code=503, body_snippet="detail")

    import collaboration_chat_bridge.main as m

    m.settings = m.Settings()
    monkeypatch.setattr(m, "post_chat", boom)

    caplog.set_level(logging.INFO, logger="collaboration_chat_bridge.main")
    transport = ASGITransport(app=m.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/teams/messages",
            json={"text": "hello", "tenant_id": "demo", "analyst_id": "analyst-1"},
            headers={"X-Bridge-Secret": "tsec", "X-Request-Id": "req-ing-fail-1"},
        )
    assert resp.status_code == 200
    audit_payloads = []
    for rec in caplog.records:
        msg = rec.getMessage()
        if msg.startswith("bridge_ingress_audit "):
            audit_payloads.append(json.loads(msg.split(" ", 1)[1]))
    hit = [p for p in audit_payloads if p.get("route") == "teams_messages" and p.get("outcome") == "unavailable"]
    assert hit
    assert hit[0]["correlation_id"] == "req-ing-fail-1"
    assert hit[0]["status_code"] == 200
    assert hit[0]["upstream_status"] == 503


@pytest.mark.asyncio
async def test_teams_activity_message(monkeypatch):
    monkeypatch.setenv("TEAMS_BRIDGE_SECRET", "tsec")
    seen: dict[str, object] = {}

    async def fake_post_chat(*_a, **_k):
        seen.update(_k)
        return {"reply": "Hi", "turn_id": "1", "answer_sections": {}}

    import collaboration_chat_bridge.main as m

    m.settings = m.Settings()
    monkeypatch.setattr(m, "post_chat", fake_post_chat)

    transport = ASGITransport(app=m.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/v1/teams/activity",
            json={"type": "message", "text": "ping", "from": {"id": "user-9"}},
            headers={"X-Bridge-Secret": "tsec", "X-Request-Id": "req-teams-2"},
        )
    assert r.status_code == 200
    assert r.json().get("ok") is True
    assert r.headers.get("x-correlation-id") == "req-teams-2"
    assert seen.get("correlation_id") == "req-teams-2"


@pytest.mark.asyncio
async def test_lark_event_forwards_correlation_to_background_turn(monkeypatch):
    monkeypatch.setenv("LARK_VERIFICATION_TOKEN", "lvtok")
    seen: dict[str, object] = {}

    async def fake_lark_reply_task(_settings, _analyst_id, _text, _event, correlation_id=None):
        seen["correlation_id"] = correlation_id

    import collaboration_chat_bridge.main as m

    m.settings = m.Settings()
    monkeypatch.setattr(m, "_lark_reply_task", fake_lark_reply_task)

    payload = {
        "token": "lvtok",
        "header": {"event_type": "im.message.receive_v1"},
        "event": {
            "message": {
                "chat_id": "oc_test",
                "content": json.dumps({"text": "hello"}),
            },
            "sender": {"sender_id": {"open_id": "ou_1"}},
        },
    }
    transport = ASGITransport(app=m.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/v1/lark/event", json=payload, headers={"X-Request-Id": "req-lark-1"})
    assert r.status_code == 200
    assert r.headers.get("x-correlation-id") == "req-lark-1"
    assert seen.get("correlation_id") == "req-lark-1"


@pytest.mark.asyncio
async def test_teams_ingress_audit_logs(monkeypatch, caplog):
    monkeypatch.setenv("TEAMS_BRIDGE_SECRET", "tsec")

    async def fake_post_chat(*_a, **_k):
        return {"reply": "Hi", "turn_id": "1", "answer_sections": {}}

    import collaboration_chat_bridge.main as m

    m.settings = m.Settings()
    monkeypatch.setattr(m, "post_chat", fake_post_chat)

    caplog.set_level(logging.INFO, logger="collaboration_chat_bridge.main")
    transport = ASGITransport(app=m.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/teams/messages",
            json={"text": "hello", "tenant_id": "demo", "analyst_id": "analyst-1"},
            headers={"X-Bridge-Secret": "tsec", "X-Request-Id": "req-ing-1"},
        )
    assert resp.status_code == 200
    audit_payloads = []
    for rec in caplog.records:
        msg = rec.getMessage()
        if msg.startswith("bridge_ingress_audit "):
            audit_payloads.append(json.loads(msg.split(" ", 1)[1]))
    hit = [p for p in audit_payloads if p.get("route") == "teams_messages" and p.get("outcome") == "success"]
    assert hit
    assert hit[0]["correlation_id"] == "req-ing-1"
    assert hit[0]["tenant_id"] == "demo"
    assert hit[0]["analyst_id"] == "analyst-1"


@pytest.mark.asyncio
async def test_slack_ingress_audit_logs(monkeypatch, caplog):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "shh")

    async def fake_process(_settings, _raw_body):
        return {
            "_async_slack": True,
            "channel": "C123",
            "user": "U123",
            "text": "hello",
            "thread_ts": "1.1",
            "ts": "1.1",
            "files": [],
            "team_id": "T1",
        }

    async def fake_run_slack_turn(_settings, _meta):
        return None

    import collaboration_chat_bridge.main as m

    m.settings = m.Settings()
    monkeypatch.setattr(m, "process_slack_event_payload", fake_process)
    monkeypatch.setattr(m, "run_slack_turn", fake_run_slack_turn)

    caplog.set_level(logging.INFO, logger="collaboration_chat_bridge.main")
    ts = str(int(time.time()))
    body = json.dumps({"type": "event_callback", "team_id": "T1", "event": {"type": "app_mention"}}).encode()
    basestring = f"v0:{ts}:".encode() + body
    sig = "v0=" + hmac.new(b"shh", basestring, hashlib.sha256).hexdigest()

    transport = ASGITransport(app=m.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/slack/events",
            content=body,
            headers={
                "X-Slack-Request-Timestamp": ts,
                "X-Slack-Signature": sig,
                "X-Request-Id": "req-slack-a1",
            },
        )
    assert resp.status_code == 200
    audit_payloads = []
    for rec in caplog.records:
        msg = rec.getMessage()
        if msg.startswith("bridge_ingress_audit "):
            audit_payloads.append(json.loads(msg.split(" ", 1)[1]))
    hit = [p for p in audit_payloads if p.get("route") == "slack_events" and p.get("outcome") == "accepted"]
    assert hit
    assert hit[0]["correlation_id"] == "req-slack-a1"


@pytest.mark.asyncio
async def test_slack_async_completion_audit_logs_upstream_status(monkeypatch, caplog):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "shh")

    async def fake_process(_settings, _raw_body):
        return {
            "_async_slack": True,
            "channel": "C123",
            "user": "U123",
            "text": "hello",
            "thread_ts": "1.1",
            "ts": "1.1",
            "files": [],
            "team_id": "T1",
        }

    async def fake_run_slack_turn(_settings, _meta):
        return {
            "outcome": "unavailable",
            "upstream_status": 503,
            "tenant_id": "demo",
            "analyst_id": "slack:U123",
            "reason": "agent_unavailable",
        }

    import collaboration_chat_bridge.main as m

    m.settings = m.Settings()
    monkeypatch.setattr(m, "process_slack_event_payload", fake_process)
    monkeypatch.setattr(m, "run_slack_turn", fake_run_slack_turn)

    caplog.set_level(logging.INFO, logger="collaboration_chat_bridge.main")
    ts = str(int(time.time()))
    body = json.dumps({"type": "event_callback", "team_id": "T1", "event": {"type": "app_mention"}}).encode()
    basestring = f"v0:{ts}:".encode() + body
    sig = "v0=" + hmac.new(b"shh", basestring, hashlib.sha256).hexdigest()

    transport = ASGITransport(app=m.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/slack/events",
            content=body,
            headers={
                "X-Slack-Request-Timestamp": ts,
                "X-Slack-Signature": sig,
                "X-Request-Id": "req-slack-c1",
            },
        )
    assert resp.status_code == 200
    audit_payloads = []
    for rec in caplog.records:
        msg = rec.getMessage()
        if msg.startswith("bridge_ingress_audit "):
            audit_payloads.append(json.loads(msg.split(" ", 1)[1]))
    hit = [p for p in audit_payloads if p.get("route") == "slack_events" and p.get("outcome") == "unavailable"]
    assert hit
    assert hit[0]["correlation_id"] == "req-slack-c1"
    assert hit[0]["upstream_status"] == 503
    assert hit[0]["analyst_id"] == "slack:U123"


@pytest.mark.asyncio
async def test_lark_async_completion_audit_logs_upstream_status(monkeypatch, caplog):
    monkeypatch.setenv("LARK_VERIFICATION_TOKEN", "lvtok")

    async def fake_lark_reply_task(_settings, _analyst_id, _text, _event, correlation_id=None):
        return {
            "outcome": "unavailable",
            "upstream_status": 503,
            "tenant_id": "demo",
            "analyst_id": "lark:ou_1",
            "reason": "agent_unavailable",
        }

    import collaboration_chat_bridge.main as m

    m.settings = m.Settings()
    monkeypatch.setattr(m, "_lark_reply_task", fake_lark_reply_task)

    caplog.set_level(logging.INFO, logger="collaboration_chat_bridge.main")
    payload = {
        "token": "lvtok",
        "header": {"event_type": "im.message.receive_v1"},
        "event": {
            "message": {
                "chat_id": "oc_test",
                "content": json.dumps({"text": "hello"}),
            },
            "sender": {"sender_id": {"open_id": "ou_1"}},
        },
    }
    transport = ASGITransport(app=m.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/v1/lark/event", json=payload, headers={"X-Request-Id": "req-lark-c1"})
    assert resp.status_code == 200
    audit_payloads = []
    for rec in caplog.records:
        msg = rec.getMessage()
        if msg.startswith("bridge_ingress_audit "):
            audit_payloads.append(json.loads(msg.split(" ", 1)[1]))
    hit = [p for p in audit_payloads if p.get("route") == "lark_event" and p.get("outcome") == "unavailable"]
    assert hit
    assert hit[0]["correlation_id"] == "req-lark-c1"
    assert hit[0]["upstream_status"] == 503
    assert hit[0]["analyst_id"] == "lark:ou_1"


@pytest.mark.asyncio
async def test_plugin_session_proxy(monkeypatch):
    monkeypatch.setenv("BRIDGE_PLUGIN_SECRET", "psec")
    seen: dict[str, object] = {}

    async def fake_create_plugin_session(*_a, **_k):
        seen.update(_k)
        return {
            "token": "tok-123",
            "token_type": "plugin_session_v1",
            "expires_at": 9999999999,
            "context": {"tenant_id": "demo", "analyst_id": "analyst-1", "case_id": "case-1"},
        }

    import collaboration_chat_bridge.main as m

    m.settings = m.Settings()
    monkeypatch.setattr(m, "create_plugin_session", fake_create_plugin_session)

    transport = ASGITransport(app=m.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r_bad = await client.post(
            "/v1/plugin/session",
            json={"tenant_id": "demo", "analyst_id": "analyst-1"},
        )
        r_ok = await client.post(
            "/v1/plugin/session",
            json={"tenant_id": "demo", "analyst_id": "analyst-1", "case_id": "case-1"},
            headers={"X-Bridge-Secret": "psec", "X-Request-Id": "req-up-1"},
        )
    assert r_bad.status_code == 401
    assert isinstance(r_bad.headers.get("x-correlation-id"), str) and r_bad.headers.get("x-correlation-id")
    assert r_ok.status_code == 200
    data = r_ok.json()
    assert data["ok"] is True
    assert isinstance(data.get("correlation_id"), str) and data["correlation_id"]
    assert data["correlation_id"] == "req-up-1"
    assert r_ok.headers.get("x-correlation-id") == data["correlation_id"]
    assert data["token"] == "tok-123"
    assert data["context"]["case_id"] == "case-1"
    assert seen.get("correlation_id") == "req-up-1"


@pytest.mark.asyncio
async def test_plugin_bootstrap_proxy(monkeypatch):
    monkeypatch.setenv("BRIDGE_PLUGIN_SECRET", "psec")
    seen: dict[str, object] = {}

    async def fake_bootstrap_plugin_session(*_a, **_k):
        seen.update(_k)
        return {
            "session": {"tenant_id": "demo", "analyst_id": "analyst-1", "case_id": "case-1"},
            "governance": {"profile": "global"},
            "integration": {"contract_version": "1.3.0"},
        }

    import collaboration_chat_bridge.main as m

    m.settings = m.Settings()
    monkeypatch.setattr(m, "bootstrap_plugin_session", fake_bootstrap_plugin_session)

    transport = ASGITransport(app=m.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/v1/plugin/bootstrap",
            json={"token": "tok-123"},
            headers={"X-Bridge-Secret": "psec", "X-Request-Id": "req-up-2"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert isinstance(data.get("correlation_id"), str) and data["correlation_id"]
    assert data["correlation_id"] == "req-up-2"
    assert r.headers.get("x-correlation-id") == data["correlation_id"]
    assert data["session"]["tenant_id"] == "demo"
    assert data["integration"]["contract_version"] == "1.3.0"
    assert seen.get("correlation_id") == "req-up-2"


@pytest.mark.asyncio
async def test_plugin_session_generated_correlation_forwarded(monkeypatch):
    monkeypatch.setenv("BRIDGE_PLUGIN_SECRET", "psec")
    seen: dict[str, object] = {}

    async def fake_create_plugin_session(*_a, **_k):
        seen.update(_k)
        return {
            "token": "tok-123",
            "token_type": "plugin_session_v1",
            "expires_at": 9999999999,
            "context": {"tenant_id": "demo", "analyst_id": "analyst-1"},
        }

    import collaboration_chat_bridge.main as m

    m.settings = m.Settings()
    monkeypatch.setattr(m, "create_plugin_session", fake_create_plugin_session)

    transport = ASGITransport(app=m.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/v1/plugin/session",
            json={"tenant_id": "demo", "analyst_id": "analyst-1"},
            headers={"X-Bridge-Secret": "psec"},
        )
    assert r.status_code == 200
    cid = r.json().get("correlation_id")
    assert isinstance(cid, str) and cid
    assert r.headers.get("x-correlation-id") == cid
    assert seen.get("correlation_id") == cid


@pytest.mark.asyncio
async def test_plugin_proxy_upstream_error(monkeypatch):
    monkeypatch.setenv("BRIDGE_PLUGIN_SECRET", "psec")

    async def boom(*_a, **_k):
        raise AgentChatError("upstream down", status_code=503, body_snippet="detail")

    import collaboration_chat_bridge.main as m

    m.settings = m.Settings()
    monkeypatch.setattr(m, "create_plugin_session", boom)

    transport = ASGITransport(app=m.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/v1/plugin/session",
            json={"tenant_id": "demo", "analyst_id": "analyst-1"},
            headers={"X-Bridge-Secret": "psec"},
        )
    assert r.status_code == 502
    assert r.json().get("detail") == "plugin session unavailable"
    assert isinstance(r.headers.get("x-correlation-id"), str) and r.headers.get("x-correlation-id")


@pytest.mark.asyncio
async def test_plugin_proxy_preserves_client_status(monkeypatch):
    monkeypatch.setenv("BRIDGE_PLUGIN_SECRET", "psec")

    async def reject(*_a, **_k):
        raise AgentUpstreamError("unauthorized", status_code=401, body_snippet="bad token")

    import collaboration_chat_bridge.main as m

    m.settings = m.Settings()
    monkeypatch.setattr(m, "bootstrap_plugin_session", reject)

    transport = ASGITransport(app=m.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/v1/plugin/bootstrap",
            json={"token": "tok-123"},
            headers={"X-Bridge-Secret": "psec"},
        )
    assert r.status_code == 401
    assert r.json().get("detail") == "plugin bootstrap rejected"
    assert isinstance(r.headers.get("x-correlation-id"), str) and r.headers.get("x-correlation-id")


@pytest.mark.asyncio
async def test_plugin_audit_logs(monkeypatch, caplog):
    monkeypatch.setenv("BRIDGE_PLUGIN_SECRET", "psec")

    async def fake_create_plugin_session(*_a, **_k):
        return {
            "token": "tok-123",
            "token_type": "plugin_session_v1",
            "expires_at": 9999999999,
            "context": {"tenant_id": "demo", "analyst_id": "analyst-1", "case_id": "case-1"},
        }

    import collaboration_chat_bridge.main as m

    m.settings = m.Settings()
    monkeypatch.setattr(m, "create_plugin_session", fake_create_plugin_session)

    caplog.set_level(logging.INFO, logger="collaboration_chat_bridge.main")
    transport = ASGITransport(app=m.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/plugin/session",
            json={"tenant_id": "demo", "analyst_id": "analyst-1", "case_id": "case-1"},
            headers={"X-Bridge-Secret": "psec", "X-Request-Id": "req-42"},
        )
    assert resp.status_code == 200
    assert resp.headers.get("x-correlation-id") == "req-42"
    assert resp.json().get("correlation_id") == "req-42"
    audit_payloads = []
    for rec in caplog.records:
        msg = rec.getMessage()
        if msg.startswith("bridge_plugin_audit "):
            audit_payloads.append(json.loads(msg.split(" ", 1)[1]))
    assert audit_payloads
    success = [p for p in audit_payloads if p.get("action") == "plugin_session" and p.get("outcome") == "success"]
    assert success
    assert success[0]["correlation_id"] == "req-42"
    assert success[0]["tenant_id"] == "demo"
    assert success[0]["analyst_id"] == "analyst-1"


@pytest.mark.asyncio
async def test_plugin_audit_logs_rejected(monkeypatch, caplog):
    monkeypatch.setenv("BRIDGE_PLUGIN_SECRET", "psec")

    async def reject(*_a, **_k):
        raise AgentUpstreamError("unauthorized", status_code=401, body_snippet="bad token")

    import collaboration_chat_bridge.main as m

    m.settings = m.Settings()
    monkeypatch.setattr(m, "bootstrap_plugin_session", reject)

    caplog.set_level(logging.INFO, logger="collaboration_chat_bridge.main")
    transport = ASGITransport(app=m.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/plugin/bootstrap",
            json={"token": "tok-123"},
            headers={"X-Bridge-Secret": "psec", "X-Request-Id": "req-rej-1"},
        )
    assert resp.status_code == 401
    assert resp.headers.get("x-correlation-id") == "req-rej-1"
    audit_payloads = []
    for rec in caplog.records:
        msg = rec.getMessage()
        if msg.startswith("bridge_plugin_audit "):
            audit_payloads.append(json.loads(msg.split(" ", 1)[1]))
    rejected = [p for p in audit_payloads if p.get("action") == "plugin_bootstrap" and p.get("outcome") == "rejected"]
    assert rejected
    assert rejected[0]["status_code"] == 401
    assert rejected[0]["upstream_status"] == 401
    assert rejected[0]["correlation_id"] == "req-rej-1"


@pytest.mark.asyncio
async def test_lark_event_rate_limit(monkeypatch):
    monkeypatch.setenv("LARK_VERIFICATION_TOKEN", "lvtok")
    monkeypatch.setenv("BRIDGE_RATE_LIMIT_PER_MINUTE", "1")

    import collaboration_chat_bridge.main as m

    m.settings = m.Settings()
    m.app.state.rate_limiter = MinuteRateLimiter(1)

    payload = {
        "token": "lvtok",
        "header": {"event_type": "im.message.receive_v1"},
        "event": {
            "message": {
                "chat_id": "oc_test",
                "content": json.dumps({"text": "hello"}),
            },
            "sender": {"sender_id": {"open_id": "ou_1"}},
        },
    }

    transport = ASGITransport(app=m.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r1 = await client.post("/v1/lark/event", json=payload)
        r2 = await client.post("/v1/lark/event", json=payload)
    assert r1.status_code == 200
    assert r2.status_code == 429
