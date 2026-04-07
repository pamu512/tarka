from __future__ import annotations

import logging
from typing import Any

import httpx

from collaboration_chat_bridge.config import Settings

log = logging.getLogger(__name__)


class AgentChatError(Exception):
    """investigation-agent /v1/chat failed or was unreachable."""

    def __init__(self, message: str, *, status_code: int = 0, body_snippet: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.body_snippet = (body_snippet or "")[:800]


async def post_chat(
    settings: Settings,
    *,
    tenant_id: str,
    analyst_id: str,
    messages: list[dict[str, str]],
    case_id: str | None = None,
) -> dict[str, Any]:
    url = f"{settings.investigation_agent_url.rstrip('/')}/v1/chat"
    headers: dict[str, str] = {}
    key = (settings.investigation_agent_api_key or "").strip()
    if key:
        headers["x-api-key"] = key
    payload: dict[str, Any] = {
        "tenant_id": tenant_id[:128],
        "analyst_id": analyst_id[:128],
        "messages": messages,
    }
    if case_id:
        payload["case_id"] = case_id[:128]
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
        log.warning("investigation-agent unreachable: %s", e)
        raise AgentChatError(f"cannot reach investigation-agent: {e}", status_code=0) from e
