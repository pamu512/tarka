from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from collaboration_chat_bridge.agent_client import AgentChatError, post_chat
from collaboration_chat_bridge.config import Settings
from collaboration_chat_bridge.reply_format import (
    format_slack_blocks,
    format_slack_error_blocks,
    normalize_slack_user_text,
)

log = logging.getLogger(__name__)


async def slack_fetch_thread_messages(bot_token: str, channel: str, thread_ts: str, *, limit: int = 20) -> list[dict[str, str]]:
    """Use conversations.replies to build OpenAI-style messages (user/assistant)."""
    if not bot_token:
        return []
    url = "https://slack.com/api/conversations.replies"
    headers = {"Authorization": f"Bearer {bot_token}", "Content-Type": "application/x-www-form-urlencoded"}
    data = {"channel": channel, "ts": thread_ts, "limit": str(min(max(limit, 2), 50))}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, headers=headers, data=data)
        j = r.json()
    if not j.get("ok"):
        log.warning("slack conversations.replies failed: %s", j)
        return []
    out: list[dict[str, str]] = []
    for m in j.get("messages") or []:
        if not isinstance(m, dict):
            continue
        uid = m.get("user") or m.get("bot_id") or "?"
        raw_text = (m.get("text") or "").strip()
        text = normalize_slack_user_text(raw_text)
        if not text:
            continue
        if m.get("bot_id"):
            out.append({"role": "assistant", "content": f"[slack bot {uid}] {text}"})
        else:
            out.append({"role": "user", "content": f"[slack user {uid}] {text}"})
    return out


async def slack_post_message(bot_token: str, channel: str, thread_ts: str | None, blocks: list[dict[str, Any]]) -> None:
    url = "https://slack.com/api/chat.postMessage"
    headers = {"Authorization": f"Bearer {bot_token}", "Content-Type": "application/json"}
    payload: dict[str, Any] = {"channel": channel, "blocks": blocks}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, headers=headers, json=payload)
        j = r.json()
    if not j.get("ok"):
        log.warning("slack chat.postMessage failed: %s", j)


async def process_slack_event_payload(settings: Settings, raw_body: bytes) -> dict[str, Any] | None:
    """Parse Slack Events API body; url_verification, errors, or metadata for async handler."""
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        return {"error": "invalid_json"}

    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}

    if payload.get("type") != "event_callback":
        return None

    event = payload.get("event") or {}
    if event.get("bot_id"):
        return None
    et = event.get("type")
    if et not in ("app_mention", "message"):
        return None
    if et == "message" and event.get("channel_type") not in ("channel", "group", "im", "mpim"):
        return None
    subtype = event.get("subtype")
    if subtype in ("bot_message", "message_changed", "message_deleted"):
        return None

    channel = event.get("channel") or ""
    user = event.get("user") or "unknown_slack_user"
    text = normalize_slack_user_text((event.get("text") or "").strip())
    thread_ts = event.get("thread_ts") or event.get("ts")

    if not text or not channel:
        return None

    return {
        "_async_slack": True,
        "channel": channel,
        "user": user,
        "text": text,
        "thread_ts": thread_ts,
        "ts": event.get("ts"),
    }


async def run_slack_turn(settings: Settings, meta: dict[str, Any]) -> None:
    channel = meta["channel"]
    user = meta["user"]
    text = meta["text"]
    thread_ts = meta.get("thread_ts")
    token = (settings.slack_bot_token or "").strip()
    parent_ts = thread_ts or meta.get("ts")
    messages: list[dict[str, str]] = []
    if token and parent_ts:
        messages = await slack_fetch_thread_messages(
            token,
            channel,
            str(parent_ts),
            limit=settings.slack_max_thread_messages,
        )
    if not messages:
        messages = [{"role": "user", "content": text}]

    tenant = settings.default_tenant_id
    case_id = settings.default_case_id

    reply_thread: str | None = None
    if settings.slack_thread_under_mention:
        reply_thread = str(thread_ts) if thread_ts else str(meta.get("ts") or "")
    else:
        reply_thread = str(thread_ts) if thread_ts else None
    if reply_thread == "":
        reply_thread = None

    try:
        agent_out = await post_chat(
            settings,
            tenant_id=tenant,
            analyst_id=f"slack:{user}"[:128],
            messages=messages,
            case_id=case_id,
        )
        blocks = format_slack_blocks(agent_out)
    except AgentChatError as e:
        log.warning("slack turn agent error: %s", e)
        blocks = format_slack_error_blocks(str(e), detail=e.body_snippet)

    if token:
        await slack_post_message(token, channel, reply_thread, blocks)
    else:
        log.warning("SLACK_BOT_TOKEN unset — cannot post reply to Slack")
