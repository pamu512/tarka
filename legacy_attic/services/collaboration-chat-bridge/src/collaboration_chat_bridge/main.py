from __future__ import annotations

import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any, Literal

import httpx
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from collaboration_chat_bridge.agent_client import (
    AgentChatError,
    AgentUpstreamError,
    bootstrap_plugin_session,
    create_plugin_session,
    post_chat,
)
from collaboration_chat_bridge.bridge_turn import (
    merge_workflow_with_explicit,
    prepare_messages_for_agent,
)
from collaboration_chat_bridge.config import Settings
from collaboration_chat_bridge.rate_limit import MinuteRateLimiter
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Distinct from investigation-agent's app.state.rate_limiter when mounted in-process.
    app.state.bridge_rate_limiter = None
    if settings.bridge_rate_limit_per_minute > 0:
        app.state.bridge_rate_limiter = MinuteRateLimiter(settings.bridge_rate_limit_per_minute)
    yield


app = FastAPI(title="Tarka Collaboration Chat Bridge", version="1.0.0", lifespan=lifespan)


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
        "plugin_bridge_secret_configured": bool(
            ((settings.bridge_plugin_secret or "").strip())
            or ((settings.teams_bridge_secret or "").strip())
        ),
        "lark_verification_configured": bool((settings.lark_verification_token or "").strip()),
        "lark_reply_configured": bool((settings.lark_tenant_access_token or "").strip()),
        "default_copilot_persona": settings.default_copilot_persona,
        "bridge_rate_limit_per_minute": settings.bridge_rate_limit_per_minute or None,
        "bridge_web_fetch_enabled": settings.bridge_web_fetch_enabled,
        "bridge_attachment_max_bytes": settings.bridge_attachment_max_bytes,
    }


@app.post("/v1/slack/events")
async def slack_events(
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    x_slack_request_timestamp: str | None = Header(default=None, alias="X-Slack-Request-Timestamp"),
    x_slack_signature: str | None = Header(default=None, alias="X-Slack-Signature"),
    x_slack_retry_num: str | None = Header(default=None, alias="X-Slack-Retry-Num"),
):
    correlation_id = _request_correlation_id(request)
    response.headers["X-Correlation-Id"] = correlation_id
    body = await request.body()
    secret = (settings.slack_signing_secret or "").strip()
    if not secret:
        _audit_ingress_event(
            route="slack_events",
            outcome="invalid",
            correlation_id=correlation_id,
            status_code=503,
            client_ip=_safe_client_ip(request),
            reason="slack_signing_secret_missing",
        )
        raise _ingress_http_exc(503, "SLACK_SIGNING_SECRET not configured", correlation_id)
    if not verify_slack_signature(
        secret, x_slack_request_timestamp or "", body, x_slack_signature or ""
    ):
        _audit_ingress_event(
            route="slack_events",
            outcome="unauthorized",
            correlation_id=correlation_id,
            status_code=401,
            client_ip=_safe_client_ip(request),
            reason="invalid_slack_signature",
        )
        raise _ingress_http_exc(401, "invalid slack signature", correlation_id)

    try:
        payload_early = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        raise _ingress_http_exc(400, "invalid json", correlation_id) from None

    if payload_early.get("type") == "url_verification":
        _audit_ingress_event(
            route="slack_events",
            outcome="challenge",
            correlation_id=correlation_id,
            status_code=200,
            client_ip=_safe_client_ip(request),
        )
        return Response(
            content=json.dumps({"challenge": payload_early.get("challenge", "")}),
            media_type="application/json",
            headers={"X-Correlation-Id": correlation_id},
        )

    if settings.bridge_rate_limit_per_minute > 0:
        lim = getattr(request.app.state, "bridge_rate_limiter", None)
        if lim:
            tid = str(payload_early.get("team_id") or "unknown")[:80]
            if not lim.allow(f"slack:{tid}"):
                _audit_ingress_event(
                    route="slack_events",
                    outcome="rate_limited",
                    correlation_id=correlation_id,
                    status_code=429,
                    client_ip=_safe_client_ip(request),
                )
                return JSONResponse(
                    status_code=429,
                    content={"detail": "rate limit exceeded"},
                    headers={"X-Correlation-Id": correlation_id},
                )

    if settings.slack_skip_retry_background and x_slack_retry_num:
        try:
            if int(x_slack_retry_num) > 0:
                log.info("slack retry delivery skipped (X-Slack-Retry-Num=%s)", x_slack_retry_num)
                _audit_ingress_event(
                    route="slack_events",
                    outcome="ignored",
                    correlation_id=correlation_id,
                    status_code=200,
                    client_ip=_safe_client_ip(request),
                    reason="slack_retry_delivery",
                )
                return {}
        except ValueError:
            pass

    pre = await process_slack_event_payload(settings, body)
    if pre and pre.get("error"):
        _audit_ingress_event(
            route="slack_events",
            outcome="invalid",
            correlation_id=correlation_id,
            status_code=400,
            client_ip=_safe_client_ip(request),
            reason=str(pre.get("error")),
        )
        raise _ingress_http_exc(400, str(pre["error"]), correlation_id)
    if isinstance(pre, dict) and pre.get("_async_slack"):
        payload = {k: v for k, v in pre.items() if k != "_async_slack"}
        payload["correlation_id"] = correlation_id
        background_tasks.add_task(_run_slack_turn_with_audit, settings, payload)
        _audit_ingress_event(
            route="slack_events",
            outcome="accepted",
            correlation_id=correlation_id,
            status_code=200,
            client_ip=_safe_client_ip(request),
            reason="async_dispatch",
        )
    else:
        _audit_ingress_event(
            route="slack_events",
            outcome="ignored",
            correlation_id=correlation_id,
            status_code=200,
            client_ip=_safe_client_ip(request),
            reason="no_action",
        )
    return {}


class TeamsBridgeBody(BaseModel):
    """Simplified inbound message (Power Automate, custom connector, or Bot Framework proxy)."""

    text: str = Field(..., max_length=16_000)
    tenant_id: str | None = Field(default=None, max_length=128)
    analyst_id: str | None = Field(default=None, max_length=128)
    case_id: str | None = Field(default=None, max_length=128)
    persona: Literal["investigation", "orchestrator"] | None = Field(
        default=None,
        description="Optional copilot persona; overrides DEFAULT_COPILOT_PERSONA and !orch / !inv message prefixes.",
    )
    thread_context: list[dict[str, str]] | None = Field(
        default=None,
        description='Prior turns, e.g. [{"role":"user","content":"..."}, ...]',
    )
    workflow_id: str | None = Field(
        default=None, max_length=80, description="Overrides !wf in message text."
    )
    workflow_params: dict[str, Any] | None = Field(
        default=None,
        description="Merged with !wfp / !style-derived params; explicit keys win.",
    )
    playbook_id: str | None = Field(default=None, max_length=64)
    batch_id: str | None = Field(default=None, max_length=128)


class PluginSessionBridgeBody(BaseModel):
    tenant_id: str = Field(..., max_length=128)
    analyst_id: str = Field(..., max_length=128)
    case_id: str | None = Field(default=None, max_length=128)
    external_case_id: str | None = Field(default=None, max_length=128)
    origin: str | None = Field(default=None, max_length=255)
    ttl_seconds: int | None = Field(default=None, ge=60, le=86_400)


class PluginBootstrapBridgeBody(BaseModel):
    token: str = Field(..., max_length=4096)


def _teams_secret_ok(x_bridge_secret: str | None) -> bool:
    expected = (settings.teams_bridge_secret or "").strip()
    if not expected:
        return False
    return constant_time_string_equals(expected, x_bridge_secret)


def _plugin_secret_ok(x_bridge_secret: str | None) -> bool:
    expected = (settings.bridge_plugin_secret or "").strip() or (
        settings.teams_bridge_secret or ""
    ).strip()
    if not expected:
        return False
    return constant_time_string_equals(expected, x_bridge_secret)


def _rate_limit_bridge_key(request: Request, prefix: str) -> None:
    if settings.bridge_rate_limit_per_minute <= 0:
        return
    lim = getattr(request.app.state, "bridge_rate_limiter", None)
    if not lim:
        return
    rip = request.client.host if request.client else "unknown"
    if not lim.allow(f"{prefix}:{rip}"):
        raise HTTPException(status_code=429, detail="rate limit exceeded")


def _plugin_upstream_status(status_code: int) -> int:
    """Map safe client-facing status for bridge-proxied plugin endpoints."""
    code = int(status_code or 0)
    if code in {400, 401, 403, 404, 409, 422, 429}:
        return code
    return 502


def _request_correlation_id(request: Request) -> str:
    rid = (
        request.headers.get("x-request-id") or request.headers.get("x-correlation-id") or ""
    ).strip()
    if rid:
        return rid[:128]
    return f"bridge-{uuid.uuid4().hex}"


def _status_class(status_code: int) -> str:
    code = int(status_code or 0)
    if 100 <= code <= 599:
        return f"{code // 100}xx"
    return "unknown"


def _safe_client_ip(request: Request | None) -> str:
    """Extract client IP for audit logs without passing Request into log sinks (CodeQL: sensitive data flow)."""
    try:
        if request and request.client and request.client.host:
            return str(request.client.host)[:128]
    except Exception:
        pass
    return "unknown"


def _audit_plugin_event(
    *,
    action: Literal["plugin_session", "plugin_bootstrap"],
    outcome: Literal["success", "unauthorized", "rate_limited", "rejected", "unavailable"],
    correlation_id: str,
    status_code: int,
    client_ip: str,
    tenant_id: str | None = None,
    analyst_id: str | None = None,
    case_id: str | None = None,
    external_case_id: str | None = None,
    upstream_status: int | None = None,
) -> None:
    payload: dict[str, Any] = {
        "event": "bridge.plugin.audit",
        "action": action,
        "outcome": outcome,
        "correlation_id": correlation_id[:128],
        "status_code": int(status_code),
        "status_class": _status_class(status_code),
        "upstream_status": int(upstream_status) if upstream_status is not None else None,
        "client_ip": client_ip[:128],
        "tenant_id": (tenant_id or "")[:128] or None,
        "analyst_id": (analyst_id or "")[:128] or None,
        "case_id": (case_id or "")[:128] or None,
        "external_case_id": (external_case_id or "")[:128] or None,
    }
    log.info("bridge_plugin_audit %s", json.dumps(payload, separators=(",", ":"), sort_keys=True))


def _audit_ingress_event(
    *,
    route: Literal["slack_events", "teams_messages", "teams_activity", "lark_event"],
    outcome: str,
    correlation_id: str,
    status_code: int,
    client_ip: str,
    tenant_id: str | None = None,
    analyst_id: str | None = None,
    reason: str | None = None,
    upstream_status: int | None = None,
) -> None:
    payload: dict[str, Any] = {
        "event": "bridge.ingress.audit",
        "route": route,
        "outcome": outcome,
        "correlation_id": correlation_id[:128],
        "status_code": int(status_code),
        "status_class": _status_class(status_code),
        "upstream_status": int(upstream_status) if upstream_status is not None else None,
        "client_ip": client_ip[:128],
        "tenant_id": (tenant_id or "")[:128] or None,
        "analyst_id": (analyst_id or "")[:128] or None,
        "reason": (reason or "")[:120] or None,
    }
    log.info("bridge_ingress_audit %s", json.dumps(payload, separators=(",", ":"), sort_keys=True))


def _audit_ingress_async_completion(
    *,
    route: Literal["slack_events", "lark_event"],
    outcome: str,
    correlation_id: str,
    status_code: int = 200,
    tenant_id: str | None = None,
    analyst_id: str | None = None,
    reason: str | None = None,
    upstream_status: int | None = None,
) -> None:
    payload: dict[str, Any] = {
        "event": "bridge.ingress.audit",
        "route": route,
        "outcome": outcome,
        "correlation_id": correlation_id[:128],
        "status_code": int(status_code),
        "status_class": _status_class(status_code),
        "upstream_status": int(upstream_status) if upstream_status is not None else None,
        "client_ip": None,
        "tenant_id": (tenant_id or "")[:128] or None,
        "analyst_id": (analyst_id or "")[:128] or None,
        "reason": (reason or "")[:120] or None,
    }
    log.info("bridge_ingress_audit %s", json.dumps(payload, separators=(",", ":"), sort_keys=True))


async def _run_slack_turn_with_audit(settings: Settings, meta: dict[str, Any]) -> None:
    correlation_id = (
        str(meta.get("correlation_id") or "").strip()[:128] or f"bridge-{uuid.uuid4().hex}"
    )
    try:
        result = await run_slack_turn(settings, meta)
        if not isinstance(result, dict):
            result = {
                "outcome": "completed",
                "reason": "async_completion",
                "upstream_status": None,
                "tenant_id": settings.default_tenant_id,
                "analyst_id": f"slack:{str(meta.get('user') or 'unknown')[:128]}",
            }
    except Exception as e:
        log.warning("slack async turn crashed: %s", type(e).__name__)
        result = {
            "outcome": "failed",
            "reason": "unexpected_error",
            "upstream_status": None,
            "tenant_id": settings.default_tenant_id,
            "analyst_id": f"slack:{str(meta.get('user') or 'unknown')[:128]}",
        }
    _audit_ingress_async_completion(
        route="slack_events",
        outcome=str(result.get("outcome") or "completed"),
        correlation_id=correlation_id,
        status_code=int(result["upstream_status"])
        if result.get("upstream_status") is not None
        else 200,
        tenant_id=str(result.get("tenant_id") or "") or None,
        analyst_id=str(result.get("analyst_id") or "") or None,
        reason=str(result.get("reason") or "async_completion"),
        upstream_status=int(result["upstream_status"])
        if result.get("upstream_status") is not None
        else None,
    )


def _extract_agent_http_status(response: JSONResponse) -> int | None:
    try:
        body = (
            response.body.decode("utf-8") if isinstance(response.body, (bytes, bytearray)) else "{}"
        )
        payload = json.loads(body)
    except Exception:
        return None
    code = payload.get("agent_http_status")
    if code is None:
        return None
    try:
        return int(code)
    except (TypeError, ValueError):
        return None


def _plugin_http_exc(status_code: int, detail: str, correlation_id: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=detail,
        headers={"X-Correlation-Id": correlation_id},
    )


def _ingress_http_exc(status_code: int, detail: str, correlation_id: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=detail,
        headers={"X-Correlation-Id": correlation_id},
    )


async def _teams_chat_result(
    *,
    tenant_id: str,
    analyst_id: str,
    case_id: str | None,
    messages: list[dict[str, str]],
    persona: str | None = None,
    workflow_id: str | None = None,
    workflow_params: dict[str, Any] | None = None,
    playbook_id: str | None = None,
    batch_id: str | None = None,
    correlation_id: str | None = None,
) -> JSONResponse | dict[str, Any]:
    try:
        msgs, wf_msg, p_msg, pers = await prepare_messages_for_agent(
            settings,
            messages,
            slack_files=[],
            slack_bot_token="",
            explicit_persona=persona,
        )
        wf_id, wf_params = merge_workflow_with_explicit(
            wf_msg,
            p_msg,
            explicit_workflow_id=workflow_id,
            explicit_params=workflow_params,
        )
        agent_out = await post_chat(
            settings,
            tenant_id=tenant_id[:128],
            analyst_id=analyst_id[:128],
            messages=msgs,
            case_id=case_id,
            persona=pers,
            messages_preprocessed=True,
            workflow_id=wf_id,
            workflow_params=wf_params if wf_params else None,
            playbook_id=playbook_id,
            batch_id=batch_id,
            correlation_id=correlation_id,
        )
    except AgentChatError as e:
        log.warning(
            "copilot_unavailable status=%s",
            e.status_code,
            exc_info=False,
        )
        safe_detail = "The investigation agent is unavailable. Retry later or check service health."
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                # Stable code for API consumers; do not echo upstream errors (stack traces / secrets).
                "error": "copilot_unavailable",
                "agent_http_status": e.status_code or None,
                "adaptive_card": format_teams_error_card("Copilot unavailable", safe_detail),
            },
        )
    return {
        "ok": True,
        "adaptive_card": format_teams_adaptive_card(agent_out),
    }


@app.post("/v1/teams/messages")
async def teams_messages(
    request: Request,
    response: Response,
    body: TeamsBridgeBody,
    x_bridge_secret: str | None = Header(default=None, alias="X-Bridge-Secret"),
):
    correlation_id = _request_correlation_id(request)
    response.headers["X-Correlation-Id"] = correlation_id
    if not _teams_secret_ok(x_bridge_secret):
        _audit_ingress_event(
            route="teams_messages",
            outcome="unauthorized",
            correlation_id=correlation_id,
            status_code=401,
            client_ip=_safe_client_ip(request),
            tenant_id=body.tenant_id or settings.default_tenant_id,
            analyst_id=body.analyst_id or "teams_user",
            reason="invalid_bridge_secret",
        )
        raise _ingress_http_exc(401, "invalid X-Bridge-Secret", correlation_id)
    if settings.bridge_rate_limit_per_minute > 0:
        lim = getattr(request.app.state, "bridge_rate_limiter", None)
        if lim:
            rip = request.client.host if request.client else "unknown"
            if not lim.allow(f"teams:{rip}"):
                _audit_ingress_event(
                    route="teams_messages",
                    outcome="rate_limited",
                    correlation_id=correlation_id,
                    status_code=429,
                    client_ip=_safe_client_ip(request),
                    tenant_id=body.tenant_id or settings.default_tenant_id,
                    analyst_id=body.analyst_id or "teams_user",
                )
                raise _ingress_http_exc(429, "rate limit exceeded", correlation_id)
    trusted_tenant = (
        request.headers.get("X-Tenant-Id") or request.headers.get("X-Tarka-Tenant-Id") or ""
    ).strip()
    trusted_analyst = (
        request.headers.get("X-Analyst-Id") or request.headers.get("X-Tarka-Analyst-Id") or ""
    ).strip()
    if settings.bridge_trusted_scope_headers_required and (
        not trusted_tenant or not trusted_analyst
    ):
        _audit_ingress_event(
            route="teams_messages",
            outcome="rejected",
            correlation_id=correlation_id,
            status_code=400,
            client_ip=_safe_client_ip(request),
            tenant_id=body.tenant_id or settings.default_tenant_id,
            analyst_id=body.analyst_id or "teams_user",
            reason="trusted_scope_headers_required",
        )
        raise _ingress_http_exc(400, "X-Tenant-Id and X-Analyst-Id are required", correlation_id)

    resolved_tenant_id = trusted_tenant or body.tenant_id or settings.default_tenant_id
    resolved_analyst_id = trusted_analyst or body.analyst_id or "teams_user"
    allowed_tenants = {
        t.strip() for t in (settings.teams_allowed_tenant_ids or "").split(",") if t.strip()
    }
    if allowed_tenants and resolved_tenant_id not in allowed_tenants:
        _audit_ingress_event(
            route="teams_messages",
            outcome="rejected",
            correlation_id=correlation_id,
            status_code=403,
            client_ip=_safe_client_ip(request),
            tenant_id=resolved_tenant_id,
            analyst_id=resolved_analyst_id,
            reason="tenant_not_allowed",
        )
        raise _ingress_http_exc(403, "tenant not allowed for teams bridge", correlation_id)

    messages = list(body.thread_context or [])
    messages.append({"role": "user", "content": body.text})
    out = await _teams_chat_result(
        tenant_id=resolved_tenant_id,
        analyst_id=resolved_analyst_id,
        case_id=body.case_id or settings.default_case_id,
        messages=messages,
        persona=body.persona,
        workflow_id=body.workflow_id,
        workflow_params=body.workflow_params,
        playbook_id=body.playbook_id,
        batch_id=body.batch_id,
        correlation_id=correlation_id,
    )
    if isinstance(out, JSONResponse):
        out.headers["X-Correlation-Id"] = correlation_id
        upstream_status = _extract_agent_http_status(out)
        _audit_ingress_event(
            route="teams_messages",
            outcome="unavailable",
            correlation_id=correlation_id,
            status_code=out.status_code,
            client_ip=_safe_client_ip(request),
            tenant_id=resolved_tenant_id,
            analyst_id=resolved_analyst_id,
            upstream_status=upstream_status,
        )
        return out
    _audit_ingress_event(
        route="teams_messages",
        outcome="success",
        correlation_id=correlation_id,
        status_code=200,
        client_ip=_safe_client_ip(request),
        tenant_id=resolved_tenant_id,
        analyst_id=resolved_analyst_id,
    )
    return out


@app.post("/v1/plugin/session")
async def plugin_session(
    request: Request,
    response: Response,
    body: PluginSessionBridgeBody,
    x_bridge_secret: str | None = Header(default=None, alias="X-Bridge-Secret"),
):
    """
    Bridge-proxied plugin session issuance for external case managers.
    Requires bridge shared secret and forwards to investigation-agent /v1/plugin/session.
    """
    correlation_id = _request_correlation_id(request)
    if not _plugin_secret_ok(x_bridge_secret):
        _audit_plugin_event(
            action="plugin_session",
            outcome="unauthorized",
            correlation_id=correlation_id,
            status_code=401,
            client_ip=_safe_client_ip(request),
            tenant_id=body.tenant_id,
            analyst_id=body.analyst_id,
            case_id=body.case_id,
            external_case_id=body.external_case_id,
        )
        raise _plugin_http_exc(401, "invalid X-Bridge-Secret", correlation_id)
    try:
        _rate_limit_bridge_key(request, "plugin")
    except HTTPException:
        _audit_plugin_event(
            action="plugin_session",
            outcome="rate_limited",
            correlation_id=correlation_id,
            status_code=429,
            client_ip=_safe_client_ip(request),
            tenant_id=body.tenant_id,
            analyst_id=body.analyst_id,
            case_id=body.case_id,
            external_case_id=body.external_case_id,
        )
        raise _plugin_http_exc(429, "rate limit exceeded", correlation_id)
    try:
        upstream = await create_plugin_session(
            settings,
            tenant_id=body.tenant_id,
            analyst_id=body.analyst_id,
            case_id=body.case_id,
            external_case_id=body.external_case_id,
            origin=body.origin,
            ttl_seconds=body.ttl_seconds,
            correlation_id=correlation_id,
        )
    except AgentUpstreamError as e:
        log.warning("plugin session upstream failure status=%s", e.status_code, exc_info=False)
        mapped = _plugin_upstream_status(e.status_code)
        _audit_plugin_event(
            action="plugin_session",
            outcome="unavailable" if mapped == 502 else "rejected",
            correlation_id=correlation_id,
            status_code=mapped,
            client_ip=_safe_client_ip(request),
            tenant_id=body.tenant_id,
            analyst_id=body.analyst_id,
            case_id=body.case_id,
            external_case_id=body.external_case_id,
            upstream_status=e.status_code,
        )
        detail = "plugin session unavailable" if mapped == 502 else "plugin session rejected"
        raise _plugin_http_exc(mapped, detail, correlation_id) from None
    _audit_plugin_event(
        action="plugin_session",
        outcome="success",
        correlation_id=correlation_id,
        status_code=200,
        client_ip=_safe_client_ip(request),
        tenant_id=body.tenant_id,
        analyst_id=body.analyst_id,
        case_id=body.case_id,
        external_case_id=body.external_case_id,
    )
    response.headers["X-Correlation-Id"] = correlation_id
    return {"ok": True, "correlation_id": correlation_id, **upstream}


@app.post("/v1/plugin/bootstrap")
async def plugin_bootstrap(
    request: Request,
    response: Response,
    body: PluginBootstrapBridgeBody,
    x_bridge_secret: str | None = Header(default=None, alias="X-Bridge-Secret"),
):
    """
    Bridge-proxied plugin token bootstrap validation.
    Requires bridge shared secret and forwards to investigation-agent /v1/plugin/bootstrap.
    """
    correlation_id = _request_correlation_id(request)
    if not _plugin_secret_ok(x_bridge_secret):
        _audit_plugin_event(
            action="plugin_bootstrap",
            outcome="unauthorized",
            correlation_id=correlation_id,
            status_code=401,
            client_ip=_safe_client_ip(request),
        )
        raise _plugin_http_exc(401, "invalid X-Bridge-Secret", correlation_id)
    try:
        _rate_limit_bridge_key(request, "plugin")
    except HTTPException:
        _audit_plugin_event(
            action="plugin_bootstrap",
            outcome="rate_limited",
            correlation_id=correlation_id,
            status_code=429,
            client_ip=_safe_client_ip(request),
        )
        raise _plugin_http_exc(429, "rate limit exceeded", correlation_id)
    try:
        upstream = await bootstrap_plugin_session(
            settings, token=body.token, correlation_id=correlation_id
        )
    except AgentUpstreamError as e:
        log.warning("plugin bootstrap upstream failure status=%s", e.status_code, exc_info=False)
        mapped = _plugin_upstream_status(e.status_code)
        _audit_plugin_event(
            action="plugin_bootstrap",
            outcome="unavailable" if mapped == 502 else "rejected",
            correlation_id=correlation_id,
            status_code=mapped,
            client_ip=_safe_client_ip(request),
            upstream_status=e.status_code,
        )
        detail = "plugin bootstrap unavailable" if mapped == 502 else "plugin bootstrap rejected"
        raise _plugin_http_exc(mapped, detail, correlation_id) from None
    session = upstream.get("session") if isinstance(upstream.get("session"), dict) else {}
    _audit_plugin_event(
        action="plugin_bootstrap",
        outcome="success",
        correlation_id=correlation_id,
        status_code=200,
        client_ip=_safe_client_ip(request),
        tenant_id=str(session.get("tenant_id") or "") or None,
        analyst_id=str(session.get("analyst_id") or "") or None,
        case_id=str(session.get("case_id") or "") or None,
        external_case_id=str(session.get("external_case_id") or "") or None,
    )
    response.headers["X-Correlation-Id"] = correlation_id
    return {"ok": True, "correlation_id": correlation_id, **upstream}


class TeamsActivityBody(BaseModel):
    """Subset of Bot Framework Activity for inbound messages."""

    model_config = ConfigDict(populate_by_name=True)

    type: str | None = None
    text: str | None = Field(default=None, max_length=16_000)
    from_: dict[str, Any] | None = Field(default=None, alias="from")


@app.post("/v1/teams/activity")
async def teams_activity(
    request: Request,
    response: Response,
    body: TeamsActivityBody,
    x_bridge_secret: str | None = Header(default=None, alias="X-Bridge-Secret"),
):
    """
    Accept a Bot Framework–shaped **message** activity from a gateway you trust.
    Same `X-Bridge-Secret` as `/v1/teams/messages`.
    """
    correlation_id = _request_correlation_id(request)
    response.headers["X-Correlation-Id"] = correlation_id
    if not _teams_secret_ok(x_bridge_secret):
        _audit_ingress_event(
            route="teams_activity",
            outcome="unauthorized",
            correlation_id=correlation_id,
            status_code=401,
            client_ip=_safe_client_ip(request),
            tenant_id=settings.default_tenant_id,
            reason="invalid_bridge_secret",
        )
        raise _ingress_http_exc(401, "invalid X-Bridge-Secret", correlation_id)
    if settings.bridge_rate_limit_per_minute > 0:
        lim = getattr(request.app.state, "bridge_rate_limiter", None)
        if lim:
            rip = request.client.host if request.client else "unknown"
            if not lim.allow(f"teams:{rip}"):
                _audit_ingress_event(
                    route="teams_activity",
                    outcome="rate_limited",
                    correlation_id=correlation_id,
                    status_code=429,
                    client_ip=_safe_client_ip(request),
                    tenant_id=settings.default_tenant_id,
                )
                raise _ingress_http_exc(429, "rate limit exceeded", correlation_id)
    if (body.type or "").lower() != "message":
        _audit_ingress_event(
            route="teams_activity",
            outcome="ignored",
            correlation_id=correlation_id,
            status_code=200,
            client_ip=_safe_client_ip(request),
            tenant_id=settings.default_tenant_id,
            reason="not_message_activity",
        )
        return {"ok": True, "ignored": True, "reason": "not a message activity"}
    text = (body.text or "").strip()
    if not text:
        _audit_ingress_event(
            route="teams_activity",
            outcome="ignored",
            correlation_id=correlation_id,
            status_code=200,
            client_ip=_safe_client_ip(request),
            tenant_id=settings.default_tenant_id,
            reason="empty_text",
        )
        return {"ok": True, "ignored": True, "reason": "empty text"}
    uid = "teams_user"
    if body.from_ and isinstance(body.from_.get("id"), str):
        uid = body.from_["id"][:128]
    out = await _teams_chat_result(
        tenant_id=settings.default_tenant_id,
        analyst_id=f"teams:{uid}",
        case_id=settings.default_case_id,
        messages=[{"role": "user", "content": text}],
        persona=None,
        workflow_id=None,
        workflow_params=None,
        playbook_id=None,
        batch_id=None,
        correlation_id=correlation_id,
    )
    if isinstance(out, JSONResponse):
        out.headers["X-Correlation-Id"] = correlation_id
    upstream_status = _extract_agent_http_status(out) if isinstance(out, JSONResponse) else None
    _audit_ingress_event(
        route="teams_activity",
        outcome="unavailable" if isinstance(out, JSONResponse) else "success",
        correlation_id=correlation_id,
        status_code=out.status_code if isinstance(out, JSONResponse) else 200,
        client_ip=_safe_client_ip(request),
        tenant_id=settings.default_tenant_id,
        analyst_id=f"teams:{uid}",
        upstream_status=upstream_status,
    )
    return out


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
async def lark_event(request: Request, response: Response, background_tasks: BackgroundTasks):
    correlation_id = _request_correlation_id(request)
    response.headers["X-Correlation-Id"] = correlation_id
    raw = await request.json()
    if not isinstance(raw, dict):
        _audit_ingress_event(
            route="lark_event",
            outcome="invalid",
            correlation_id=correlation_id,
            status_code=400,
            client_ip=_safe_client_ip(request),
            reason="expected_json_object",
        )
        raise _ingress_http_exc(400, "expected JSON object", correlation_id)

    if raw.get("type") == "url_verification" or raw.get("challenge") is not None:
        ch = raw.get("challenge")
        if ch is not None:
            _audit_ingress_event(
                route="lark_event",
                outcome="challenge",
                correlation_id=correlation_id,
                status_code=200,
                client_ip=_safe_client_ip(request),
            )
            return {"challenge": ch}

    wrap = LarkEventWrapper.model_validate(raw)
    if wrap.header and wrap.header.get("event_type") == "im.message.receive_v1":
        vtok = (settings.lark_verification_token or "").strip()
        if vtok and wrap.token != vtok:
            _audit_ingress_event(
                route="lark_event",
                outcome="unauthorized",
                correlation_id=correlation_id,
                status_code=401,
                client_ip=_safe_client_ip(request),
                reason="invalid_lark_verification_token",
            )
            raise _ingress_http_exc(401, "invalid lark verification token", correlation_id)
        if settings.bridge_rate_limit_per_minute > 0:
            lim = getattr(request.app.state, "bridge_rate_limiter", None)
            if lim:
                rip = request.client.host if request.client else "unknown"
                if not lim.allow(f"lark:{rip}"):
                    _audit_ingress_event(
                        route="lark_event",
                        outcome="rate_limited",
                        correlation_id=correlation_id,
                        status_code=429,
                        client_ip=_safe_client_ip(request),
                    )
                    raise _ingress_http_exc(429, "rate limit exceeded", correlation_id)
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
            background_tasks.add_task(
                _lark_reply_task_with_audit, settings, str(sid), text, ev, correlation_id
            )
            _audit_ingress_event(
                route="lark_event",
                outcome="accepted",
                correlation_id=correlation_id,
                status_code=200,
                client_ip=_safe_client_ip(request),
                analyst_id=f"lark:{sid}",
                reason="async_dispatch",
            )
        else:
            _audit_ingress_event(
                route="lark_event",
                outcome="ignored",
                correlation_id=correlation_id,
                status_code=200,
                client_ip=_safe_client_ip(request),
                reason="empty_text",
            )
    else:
        _audit_ingress_event(
            route="lark_event",
            outcome="ignored",
            correlation_id=correlation_id,
            status_code=200,
            client_ip=_safe_client_ip(request),
            reason="unsupported_event_type",
        )
    return {}


async def _lark_reply_task(
    settings: Settings,
    analyst_id: str,
    text: str,
    event: dict[str, Any],
    correlation_id: str | None = None,
) -> dict[str, Any]:
    outcome = "success"
    reason: str | None = None
    upstream_status: int | None = None
    messages = [{"role": "user", "content": text}]
    try:
        msgs, wf_msg, p_msg, pers = await prepare_messages_for_agent(
            settings,
            messages,
            slack_files=[],
            slack_bot_token="",
            explicit_persona=None,
        )
        wf_id, wf_params = merge_workflow_with_explicit(
            wf_msg,
            p_msg,
            explicit_workflow_id=None,
            explicit_params=None,
        )
        agent_out = await post_chat(
            settings,
            tenant_id=settings.default_tenant_id,
            analyst_id=f"lark:{analyst_id}"[:128],
            messages=msgs,
            case_id=settings.default_case_id,
            persona=pers,
            messages_preprocessed=True,
            workflow_id=wf_id,
            workflow_params=wf_params if wf_params else None,
            correlation_id=correlation_id,
        )
        out_text = format_lark_card_text(agent_out)
    except AgentChatError as e:
        log.warning("lark turn agent error status=%s", getattr(e, "status_code", None))
        out_text = format_lark_error_text(
            "The investigation assistant returned an error. Please try again.",
            "",
        )
        outcome = "unavailable"
        upstream_status = int(e.status_code or 0) or None
        reason = "agent_unavailable"

    msg_obj = event.get("message") if isinstance(event.get("message"), dict) else {}
    chat_id = msg_obj.get("chat_id")
    if not chat_id:
        log.warning("lark: missing chat_id, cannot post reply")
        if outcome == "success":
            outcome = "ignored"
        reason = reason or "missing_chat_id"
        return {
            "route": "lark_event",
            "outcome": outcome,
            "upstream_status": upstream_status,
            "tenant_id": settings.default_tenant_id,
            "analyst_id": f"lark:{analyst_id}"[:128],
            "reason": reason,
        }
    access = (settings.lark_tenant_access_token or "").strip()
    if not access:
        log.warning("LARK_TENANT_ACCESS_TOKEN unset — cannot post Lark reply")
        if outcome == "success":
            outcome = "ignored"
        reason = reason or "lark_token_missing"
        return {
            "route": "lark_event",
            "outcome": outcome,
            "upstream_status": upstream_status,
            "tenant_id": settings.default_tenant_id,
            "analyst_id": f"lark:{analyst_id}"[:128],
            "reason": reason,
        }
    try:
        await _lark_post_message(access, str(chat_id), out_text)
    except Exception as e:
        log.warning("lark message send failed: %s", type(e).__name__)
        if outcome == "success":
            outcome = "delivery_failed"
        reason = reason or "lark_post_failed"
    return {
        "route": "lark_event",
        "outcome": outcome,
        "upstream_status": upstream_status,
        "tenant_id": settings.default_tenant_id,
        "analyst_id": f"lark:{analyst_id}"[:128],
        "reason": reason,
    }


async def _lark_reply_task_with_audit(
    settings: Settings,
    analyst_id: str,
    text: str,
    event: dict[str, Any],
    correlation_id: str | None = None,
) -> None:
    cid = str(correlation_id or "").strip()[:128] or f"bridge-{uuid.uuid4().hex}"
    try:
        result = await _lark_reply_task(settings, analyst_id, text, event, correlation_id)
        if not isinstance(result, dict):
            result = {
                "outcome": "completed",
                "reason": "async_completion",
                "upstream_status": None,
                "tenant_id": settings.default_tenant_id,
                "analyst_id": f"lark:{analyst_id}"[:128],
            }
    except Exception as e:
        log.warning("lark async turn crashed: %s", type(e).__name__)
        result = {
            "outcome": "failed",
            "reason": "unexpected_error",
            "upstream_status": None,
            "tenant_id": settings.default_tenant_id,
            "analyst_id": f"lark:{analyst_id}"[:128],
        }
    _audit_ingress_async_completion(
        route="lark_event",
        outcome=str(result.get("outcome") or "completed"),
        correlation_id=cid,
        status_code=int(result["upstream_status"])
        if result.get("upstream_status") is not None
        else 200,
        tenant_id=str(result.get("tenant_id") or "") or None,
        analyst_id=str(result.get("analyst_id") or "") or None,
        reason=str(result.get("reason") or "async_completion"),
        upstream_status=int(result["upstream_status"])
        if result.get("upstream_status") is not None
        else None,
    )


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
