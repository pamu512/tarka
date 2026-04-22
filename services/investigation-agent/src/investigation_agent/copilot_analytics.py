from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from investigation_agent.config import Settings

"""
Optional org analytics events (PII-minimized). Opt-in via COPILOT_ANALYTICS_* settings.
"""
log = logging.getLogger(__name__)


def _analyst_hash(settings: Settings, analyst_id: str) -> str | None:
    secret = (settings.copilot_analytics_hmac_secret or "").strip()
    if not secret:
        return None
    return hmac.new(secret.encode("utf-8"), analyst_id.encode("utf-8"), hashlib.sha256).hexdigest()[:24]


def _base_payload(settings: Settings, tenant_id: str, analyst_id: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tenant_id": (tenant_id or "").strip()[:128],
    }
    ah = _analyst_hash(settings, analyst_id)
    if ah:
        out["analyst_id_hash"] = ah
    return out


async def _emit(settings: Settings, event_type: str, payload: dict[str, Any]) -> None:
    body = {"type": event_type, **payload}
    sink = settings.copilot_analytics_sink
    if sink == "log":
        log.info("%s", json.dumps({"event": "copilot_analytics", **body}, default=str))
        return
    if sink != "http":
        return
    url = (settings.copilot_analytics_webhook_url or "").strip()
    if not url:
        log.debug("copilot analytics http sink skipped: empty webhook url")
        return
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            await client.post(url, json=body)
    except Exception:
        log.warning("copilot analytics webhook failed", exc_info=True)


def schedule_emit(settings: Settings, event_type: str, payload: dict[str, Any]) -> None:
    """Fire-and-forget; does not block chat latency."""
    if not settings.copilot_analytics_enabled:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_emit(settings, event_type, payload))
        return
    loop.create_task(_emit(settings, event_type, payload))


def schedule_turn_completed(
    settings: Settings,
    *,
    tenant_id: str,
    analyst_id: str,
    turn_id: str,
    tool_invocation_count: int,
    assurance_mode: str,
    had_tool_error: bool,
    assurance_refused: bool,
    persona: str | None = None,
) -> None:
    payload = _base_payload(settings, tenant_id, analyst_id)
    p = (persona or "investigation").strip().lower()
    if p not in ("investigation", "orchestrator"):
        p = "investigation"
    payload.update(
        {
            "turn_id": (turn_id or "").strip()[:128],
            "tool_invocation_count": int(tool_invocation_count),
            "assurance_mode": (assurance_mode or "standard")[:32],
            "had_tool_error": bool(had_tool_error),
            "assurance_refused": bool(assurance_refused),
            "persona": p[:32],
        },
    )
    schedule_emit(settings, "copilot.turn.completed", payload)


def schedule_feedback_submitted(
    settings: Settings,
    *,
    tenant_id: str,
    analyst_id: str,
    turn_id: str,
    rating: int,
) -> None:
    payload = _base_payload(settings, tenant_id, analyst_id)
    payload.update(
        {
            "turn_id": (turn_id or "").strip()[:128],
            "rating": int(rating),
        },
    )
    schedule_emit(settings, "copilot.feedback.submitted", payload)
