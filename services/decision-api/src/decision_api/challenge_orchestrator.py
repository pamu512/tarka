"""Map recommended_action → tenant challenge webhook (Wave 4).

Audit must already be committed before calling ``maybe_dispatch_challenge_webhook``.
Does not invent SMS/WebAuthn providers — fires a signed JSON callback the tenant owns.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Any

import httpx

log = logging.getLogger("decision-api.challenge")

_STEP_UP_ACTIONS = frozenset(
    {
        "step_up_mfa",
        "step_up_attestation",
        "step_up_auth",
        "challenge",
        "step_up",
    }
)


def challenge_webhook_configured() -> bool:
    return bool(os.environ.get("TARKA_CHALLENGE_WEBHOOK_URL", "").strip())


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


async def maybe_dispatch_challenge_webhook(
    *,
    http: httpx.AsyncClient,
    trace_id: str,
    tenant_id: str,
    entity_id: str,
    decision: str,
    recommended_action: str,
    challenge_metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """POST challenge intent to tenant URL when action is step-up class.

    Returns delivery summary or None when not configured / not applicable.
    """
    action = (recommended_action or "").strip().lower()
    if action not in _STEP_UP_ACTIONS:
        return None
    url = os.environ.get("TARKA_CHALLENGE_WEBHOOK_URL", "").strip()
    if not url:
        return None
    secret = os.environ.get("TARKA_CHALLENGE_WEBHOOK_SECRET", "").strip()
    payload = {
        "schema_id": "tarka.challenge_webhook/v1",
        "trace_id": trace_id,
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "decision": decision,
        "recommended_action": recommended_action,
        "challenge_metadata": challenge_metadata or {},
        "step_up_url_hint": (challenge_metadata or {}).get("step_up_url"),
    }
    import json

    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    headers = {"content-type": "application/json", "x-tarka-challenge-event": "step_up"}
    if secret:
        headers["x-tarka-signature"] = _sign(raw, secret)
    try:
        r = await http.post(url, content=raw, headers=headers, timeout=5.0)
        return {
            "dispatched": True,
            "status_code": r.status_code,
            "ok": 200 <= r.status_code < 300,
            "url_host": httpx.URL(url).host,
        }
    except Exception as e:
        log.warning("challenge webhook failed trace=%s: %s", trace_id, e)
        return {
            "dispatched": True,
            "ok": False,
            "error": str(e)[:200],
        }
