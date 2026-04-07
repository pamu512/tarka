from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from collaboration_chat_bridge.agent_client import AgentChatError, post_chat
from collaboration_chat_bridge.config import Settings
from collaboration_chat_bridge.reply_format import (
    format_lark_card_text,
    format_lark_error_text,
    format_teams_adaptive_card,
    format_teams_error_card,
)
from collaboration_chat_bridge.secrets_util import constant_time_string_equals
from collaboration_chat_bridge.slack_events import process_slack_event_payload, run_slack_turn
from collaboration_chat_bridge.slack_verify import verify_slack_signature

log = logging.getLogger(__name__)
settings = Settings()
app = FastAPI(title="Tarka Collaboration Chat Bridge", version="1.0.0")


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.get("/v1/health")
async def health():
    return {
        "status": "ok",
        "service": "collaboration-chat-bridge",
        "investigation_agent_configured": bool(settings.investigation_agent_url),
        "slack_signing_configured": bool((settings.slack_signing_secret or "").strip()),
        "slack_bot_configured": bool((settings.slack_bot_token or "").strip()),
        "slack_skip_retry_background": settings.slack_skip_retry_background,
        "slack_thread_under_mention": settings.slack_thread_under_mention,
        "teams_bridge_secret_configured": bool((settings.teams_bridge_secret or "").strip()),
        "lark_verification_configured": bool((settings.lark_verification_token or "").strip()),
        "lark_reply_configured": bool((settings.lark_tenant_access_token or "").strip()),
    }


@app.post("/v1/slack/events")
async def slack_events(
    request: Request,
    background_tasks: BackgroundTasks,
    x_slack_request_timestamp: str | None = Header(default=None, alias="X-Slack-Request-Timestamp"),
    x_slack_signature: str | None = Header(default=None, alias="X-Slack-Signature"),
    x_slack_retry_num: str | None = Header(default=None, alias="X-Slack-Retry-Num"),
):
    body = await request.body()
    secret = (settings.slack_signing_secret or "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="SLACK_SIGNING_SECRET not configured")
    if not verify_slack_signature(secret, x_slack_request_timestamp or "", body, x_slack_signature or ""):
        raise HTTPException(status_code=401, detail="invalid slack signature")

    if settings.slack_skip_retry_background and x_slack_retry_num:
        try:
            if int(x_slack_retry_num) > 0:
                log.info("slack retry delivery skipped (X-Slack-Retry-Num=%s)", x_slack_retry_num)
                return {}
        except ValueError:
            pass

    pre = await process_slack_event_payload(settings, body)
    if pre and "challenge" in pre:
        return Response(content=json.dumps(pre), media_type="application/json")
    if pre and pre.get("error"):
        raise HTTPException(status_code=400, detail=pre["error"])
    if isinstance(pre, dict) and pre.get("_async_slack"):
        background_tasks.add_task(run_slack_turn, settings, {k: v for k, v in pre.items() if k != "_async_slack"})
    return {}


class TeamsBridgeBody(BaseModel):
    """Simplified inbound message (Power Automate, custom connector, or Bot Framework proxy)."""

    text: str = Field(..., max_length=16_000)
    tenant_id: str | None = Field(default=None, max_length=128)
    analyst_id: str | None = Field(default=None, max_length=128)
    case_id: str | None = Field(default=None, max_length=128)
    thread_context: list[dict[str, str]] | None = Field(
        default=None,
        description='Prior turns, e.g. [{"role":"user","content":"..."}, ...]',
    )


def _teams_secret_ok(x_bridge_secret: str | None) -> bool:
    expected = (settings.teams_bridge_secret or "").strip()
    if not expected:
        return False
    return constant_time_string_equals(expected, x_bridge_secret)


async def _teams_chat_result(
    *,
    tenant_id: str,
    analyst_id: str,
    case_id: str | None,
    messages: list[dict[str, str]],
) -> JSONResponse | dict[str, Any]:
    try:
        agent_out = await post_chat(
            settings,
            tenant_id=tenant_id[:128],
            analyst_id=analyst_id[:128],
            messages=messages,
            case_id=case_id,
        )
    except AgentChatError as e:
        detail = str(e)
        if e.body_snippet:
            detail = f"{detail}\n{e.body_snippet}"
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "error": str(e),
                "adaptive_card": format_teams_error_card("Copilot unavailable", detail),
            },
        )
    return {
        "ok": True,
        "adaptive_card": format_teams_adaptive_card(agent_out),
        "raw": agent_out,
    }


@app.post("/v1/teams/messages")
async def teams_messages(
    body: TeamsBridgeBody,
    x_bridge_secret: str | None = Header(default=None, alias="X-Bridge-Secret"),
):
    if not _teams_secret_ok(x_bridge_secret):
        raise HTTPException(status_code=401, detail="invalid X-Bridge-Secret")
    messages = list(body.thread_context or [])
    messages.append({"role": "user", "content": body.text})
    out = await _teams_chat_result(
        tenant_id=body.tenant_id or settings.default_tenant_id,
        analyst_id=body.analyst_id or "teams_user",
        case_id=body.case_id or settings.default_case_id,
        messages=messages,
    )
    if isinstance(out, JSONResponse):
        return out
    return out


class TeamsActivityBody(BaseModel):
    """Subset of Bot Framework Activity for inbound messages."""

    model_config = ConfigDict(populate_by_name=True)

    type: str | None = None
    text: str | None = Field(default=None, max_length=16_000)
    from_: dict[str, Any] | None = Field(default=None, alias="from")


@app.post("/v1/teams/activity")
async def teams_activity(
    body: TeamsActivityBody,
    x_bridge_secret: str | None = Header(default=None, alias="X-Bridge-Secret"),
):
    """
    Accept a Bot Framework–shaped **message** activity from a gateway you trust.
    Same `X-Bridge-Secret` as `/v1/teams/messages`.
    """
    if not _teams_secret_ok(x_bridge_secret):
        raise HTTPException(status_code=401, detail="invalid X-Bridge-Secret")
    if (body.type or "").lower() != "message":
        return {"ok": True, "ignored": True, "reason": "not a message activity"}
    text = (body.text or "").strip()
    if not text:
        return {"ok": True, "ignored": True, "reason": "empty text"}
    uid = "teams_user"
    if body.from_ and isinstance(body.from_.get("id"), str):
        uid = body.from_["id"][:128]
    return await _teams_chat_result(
        tenant_id=settings.default_tenant_id,
        analyst_id=f"teams:{uid}",
        case_id=settings.default_case_id,
        messages=[{"role": "user", "content": text}],
    )


class LarkEventWrapper(BaseModel):
    """Lark event callback (non-encrypted)."""

    model_config = ConfigDict(populate_by_name=True)

    challenge: str | None = None
    token: str | None = None
    type: str | None = None
    lark_schema: str | None = Field(default=None, alias="schema")
    header: dict[str, Any] | None = None
    event: dict[str, Any] | None = None


@app.post("/v1/lark/event")
async def lark_event(request: Request, background_tasks: BackgroundTasks):
    raw = await request.json()
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="expected JSON object")

    if raw.get("type") == "url_verification" or raw.get("challenge") is not None:
        ch = raw.get("challenge")
        if ch is not None:
            return {"challenge": ch}

    wrap = LarkEventWrapper.model_validate(raw)
    if wrap.header and wrap.header.get("event_type") == "im.message.receive_v1":
        vtok = (settings.lark_verification_token or "").strip()
        if vtok and wrap.token != vtok:
            raise HTTPException(status_code=401, detail="invalid lark verification token")
        ev = wrap.event or {}
        msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}
        content_raw = msg.get("content") or "{}"
        try:
            content = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
        except json.JSONDecodeError:
            content = {}
        text = (content.get("text") or "").strip()
        sender = ev.get("sender") if isinstance(ev.get("sender"), dict) else {}
        sid = (sender.get("sender_id") or {}).get("open_id") or "lark_user"
        if text:
            background_tasks.add_task(_lark_reply_task, settings, str(sid), text, ev)
    return {}


async def _lark_reply_task(settings: Settings, analyst_id: str, text: str, event: dict[str, Any]) -> None:
    messages = [{"role": "user", "content": text}]
    try:
        agent_out = await post_chat(
            settings,
            tenant_id=settings.default_tenant_id,
            analyst_id=f"lark:{analyst_id}"[:128],
            messages=messages,
            case_id=settings.default_case_id,
        )
        out_text = format_lark_card_text(agent_out)
    except AgentChatError as e:
        log.warning("lark turn agent error: %s", e)
        out_text = format_lark_error_text(str(e), e.body_snippet)

    msg_obj = event.get("message") if isinstance(event.get("message"), dict) else {}
    chat_id = msg_obj.get("chat_id")
    if not chat_id:
        log.warning("lark: missing chat_id, cannot post reply")
        return
    access = (settings.lark_tenant_access_token or "").strip()
    if not access:
        log.warning("LARK_TENANT_ACCESS_TOKEN unset — cannot post Lark reply")
        return
    await _lark_post_message(access, str(chat_id), out_text)


async def _lark_post_message(tenant_access_token: str, chat_id: str, text: str) -> None:
    url = "https://open.feishu.cn/open-apis/im/v1/messages"
    headers = {"Authorization": f"Bearer {tenant_access_token}", "Content-Type": "application/json"}
    payload = {
        "receive_id_type": "chat_id",
        "receive_id": chat_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}),
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, headers=headers, json=payload)
        j = r.json()
    if j.get("code") != 0:
        log.warning("lark message post failed: %s", j)
