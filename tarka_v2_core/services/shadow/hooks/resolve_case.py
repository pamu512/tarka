"""Autonomous resolution: call orchestrator case transition when Shadow AI confidence is high enough."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final

import httpx

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD: Final[float] = 0.95
RESOLVED_AUTO_STATUS: Final[str] = "RESOLVED_AUTO"
DEFAULT_REASON_CODE: Final[str] = "SHADOW_AI_AUTO_RESOLVE"


@dataclass(frozen=True)
class AutoresolveOutcome:
    """Result of :func:`maybe_autoresolve_lifecycle_case`."""

    called_api: bool
    """True if confidence was above threshold and an HTTP request was sent."""

    http_status: int | None
    response_json: dict[str, Any] | None
    skipped_reason: str | None
    """Set when no request was sent (e.g. low confidence)."""


async def maybe_autoresolve_lifecycle_case(
    *,
    orchestrator_base_url: str,
    case_id: str,
    confidence: float,
    auth_token: str,
    reason_code: str = DEFAULT_REASON_CODE,
    client: httpx.AsyncClient | None = None,
    timeout_s: float = 30.0,
) -> AutoresolveOutcome:
    """
    If ``confidence`` is strictly greater than :data:`CONFIDENCE_THRESHOLD`, ``PUT`` the Case Transition
    API to move the lifecycle case to :data:`RESOLVED_AUTO_STATUS`.

    Otherwise returns immediately without calling the API. The caller supplies a service token via
    ``auth_token`` (sent as ``X-Auth-Token``).
    """
    if not (confidence > CONFIDENCE_THRESHOLD):
        return AutoresolveOutcome(False, None, None, "confidence_not_above_threshold")

    base = (orchestrator_base_url or "").strip().rstrip("/")
    cid = (case_id or "").strip()
    tok = (auth_token or "").strip()
    rc = (reason_code or "").strip() or DEFAULT_REASON_CODE

    url = f"{base}/v1/cases/{cid}/status"
    payload = {"status": RESOLVED_AUTO_STATUS, "reason_code": rc}
    headers = {"X-Auth-Token": tok}

    if client is not None:
        resp = await client.put(url, json=payload, headers=headers)
        return _outcome_from_response(resp)

    timeout = httpx.Timeout(timeout_s)
    async with httpx.AsyncClient(timeout=timeout) as owned:
        resp = await owned.put(url, json=payload, headers=headers)
        return _outcome_from_response(resp)


def _outcome_from_response(resp: httpx.Response) -> AutoresolveOutcome:
    body: dict[str, Any] | None = None
    try:
        parsed = resp.json()
        if isinstance(parsed, dict):
            body = parsed
    except ValueError:
        body = None

    if resp.status_code != 200:
        logger.warning(
            "shadow_autoresolve_case_transition_non_200 status=%s case_id_in_url body_keys=%s",
            resp.status_code,
            list(body.keys()) if body else None,
        )
    return AutoresolveOutcome(True, resp.status_code, body, None)
