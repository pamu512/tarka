from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from collaboration_chat_bridge.agent_client import AgentChatError
from collaboration_chat_bridge.main import app
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


@pytest.mark.asyncio
async def test_teams_bridge_secret(monkeypatch):
    monkeypatch.setenv("TEAMS_BRIDGE_SECRET", "tsec")

    async def fake_post_chat(*_a, **_k):
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
        r_ok = await client.post(
            "/v1/teams/messages",
            json={"text": "hello", "analyst_id": "u1"},
            headers={"X-Bridge-Secret": "tsec"},
        )
    assert r_ok.status_code == 200
    data = r_ok.json()
    assert data.get("ok") is True
    assert "adaptive_card" in data
    assert data["raw"]["turn_id"] == "turn-test"


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
    assert "adaptive_card" in data


@pytest.mark.asyncio
async def test_teams_activity_message(monkeypatch):
    monkeypatch.setenv("TEAMS_BRIDGE_SECRET", "tsec")

    async def fake_post_chat(*_a, **_k):
        return {"reply": "Hi", "turn_id": "1", "answer_sections": {}}

    import collaboration_chat_bridge.main as m

    m.settings = m.Settings()
    monkeypatch.setattr(m, "post_chat", fake_post_chat)

    transport = ASGITransport(app=m.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/v1/teams/activity",
            json={"type": "message", "text": "ping", "from": {"id": "user-9"}},
            headers={"X-Bridge-Secret": "tsec"},
        )
    assert r.status_code == 200
    assert r.json().get("ok") is True
