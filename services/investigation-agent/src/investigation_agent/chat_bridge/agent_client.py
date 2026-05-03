from __future__ import annotations

import logging
from typing import Any

import httpx

from investigation_agent.chat_bridge.config import Settings
from investigation_agent.chat_bridge.persona_bridge import resolve_copilot_persona_for_bridge

log = logging.getLogger(__name__)


class AgentUpstreamError(Exception):
    """investigation-agent upstream call failed or was unreachable."""

    def __init__(self, message: str, *, status_code: int = 0, body_snippet: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.body_snippet = (body_snippet or "")[:800]


class AgentChatError(AgentUpstreamError):
    """investigation-agent /v1/chat failed or was unreachable."""


def _agent_headers(settings: Settings, *, correlation_id: str | None = None) -> dict[str, str]:
    headers: dict[str, str] = {}
    key = (settings.investigation_agent_api_key or "").strip()
    if key:
        headers["x-api-key"] = key
    cid = (correlation_id or "").strip()
    if cid:
        headers["x-request-id"] = cid[:128]
        headers["x-correlation-id"] = cid[:128]
    return headers


async def post_chat(
    settings: Settings,
    *,
    tenant_id: str,
    analyst_id: str,
    messages: list[dict[str, str]],
    case_id: str | None = None,
    persona: str | None = None,
    workflow_id: str | None = None,
    workflow_params: dict[str, Any] | None = None,
    playbook_id: str | None = None,
    batch_id: str | None = None,
    messages_preprocessed: bool = False,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    url = f"{settings.investigation_agent_url.rstrip('/')}/v1/chat"
    headers = _agent_headers(settings, correlation_id=correlation_id)
    if messages_preprocessed:
        eff_persona = (persona or "investigation").strip().lower()
        if eff_persona not in ("investigation", "orchestrator"):
            eff_persona = "investigation"
        eff_messages = messages
    else:
        eff_persona, eff_messages = resolve_copilot_persona_for_bridge(
            settings.default_copilot_persona,
            messages,
            explicit=persona,
        )
    payload: dict[str, Any] = {
        "tenant_id": tenant_id[:128],
        "analyst_id": analyst_id[:128],
        "messages": eff_messages,
        "persona": eff_persona,
    }
    if case_id:
        payload["case_id"] = case_id[:128]
    if workflow_id and str(workflow_id).strip():
        payload["workflow_id"] = str(workflow_id).strip()[:80]
    if workflow_params:
        payload["workflow_params"] = workflow_params
    if playbook_id and str(playbook_id).strip():
        payload["playbook_id"] = str(playbook_id).strip()[:64]
    if batch_id and str(batch_id).strip():
        payload["batch_id"] = str(batch_id).strip()[:128]
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=15.0)) as client:
            r = await client.post(url, json=payload, headers=headers)
            if r.status_code >= 400:
                log.warning(
                    "investigation-agent chat HTTP %s: %s",
                    r.status_code,
                    r.text[:500],
                )
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        resp = e.response
        snippet = (resp.text[:800] if resp is not None else "") or ""
        code = resp.status_code if resp is not None else 0
        raise AgentChatError(
            f"investigation-agent returned HTTP {code}",
            status_code=code,
            body_snippet=snippet,
        ) from e
    except httpx.RequestError as e:
        # Log full error server-side; keep exception message generic for clients (CodeQL py/stack-trace-exposure).
        log.warning("investigation-agent unreachable: %s", e)
        raise AgentChatError("cannot reach investigation-agent", status_code=0) from e


async def create_plugin_session(
    settings: Settings,
    *,
    tenant_id: str,
    analyst_id: str,
    case_id: str | None = None,
    external_case_id: str | None = None,
    origin: str | None = None,
    ttl_seconds: int | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    url = f"{settings.investigation_agent_url.rstrip('/')}/v1/plugin/session"
    payload: dict[str, Any] = {
        "tenant_id": tenant_id[:128],
        "analyst_id": analyst_id[:128],
    }
    if case_id:
        payload["case_id"] = case_id[:128]
    if external_case_id:
        payload["external_case_id"] = external_case_id[:128]
    if origin:
        payload["origin"] = origin[:255]
    if ttl_seconds is not None:
        payload["ttl_seconds"] = int(ttl_seconds)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            r = await client.post(url, json=payload, headers=_agent_headers(settings, correlation_id=correlation_id))
            if r.status_code >= 400:
                log.warning("investigation-agent plugin/session HTTP %s: %s", r.status_code, r.text[:500])
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, dict):
                raise AgentUpstreamError("invalid response from investigation-agent", status_code=502)
            return data
    except httpx.HTTPStatusError as e:
        resp = e.response
        raise AgentUpstreamError(
            f"investigation-agent returned HTTP {resp.status_code if resp is not None else 0}",
            status_code=resp.status_code if resp is not None else 0,
            body_snippet=resp.text[:800] if resp is not None else "",
        ) from e
    except httpx.RequestError as e:
        log.warning("investigation-agent plugin/session unreachable: %s", e)
        raise AgentUpstreamError("cannot reach investigation-agent", status_code=0) from e


async def bootstrap_plugin_session(settings: Settings, *, token: str, correlation_id: str | None = None) -> dict[str, Any]:
    url = f"{settings.investigation_agent_url.rstrip('/')}/v1/plugin/bootstrap"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            r = await client.post(
                url,
                json={"token": token[:4096]},
                headers=_agent_headers(settings, correlation_id=correlation_id),
            )
            if r.status_code >= 400:
                log.warning("investigation-agent plugin/bootstrap HTTP %s: %s", r.status_code, r.text[:500])
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, dict):
                raise AgentUpstreamError("invalid response from investigation-agent", status_code=502)
            return data
    except httpx.HTTPStatusError as e:
        resp = e.response
        raise AgentUpstreamError(
            f"investigation-agent returned HTTP {resp.status_code if resp is not None else 0}",
            status_code=resp.status_code if resp is not None else 0,
            body_snippet=resp.text[:800] if resp is not None else "",
        ) from e
    except httpx.RequestError as e:
        log.warning("investigation-agent plugin/bootstrap unreachable: %s", e)
        raise AgentUpstreamError("cannot reach investigation-agent", status_code=0) from e
