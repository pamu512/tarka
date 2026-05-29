"""Autonomous resolution: call orchestrator case transition when Shadow AI confidence is high enough."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Final

import httpx

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD: Final[float] = 0.95
RESOLVED_AUTO_STATUS: Final[str] = "RESOLVED_AUTO"
DEFAULT_REASON_CODE: Final[str] = "SHADOW_AI_AUTO_RESOLVE"

_AUTO_RESOLVE_RECOMMENDATIONS: Final[frozenset[str]] = frozenset(
    {
        "APPROVE",
        "ALLOW",
        "AUTO_RESOLVE",
        "AUTO_RESOLVE_LEGIT",
        "RESOLVED_AUTO",
        "RESOLVED_LEGIT",
        "CLEAR",
        "CLEARED",
    },
)

_CONFIDENCE_METRIC_KEYS: Final[tuple[str, ...]] = (
    "confidence",
    "p_legit",
    "p_clear",
    "auto_resolve_confidence",
    "model_confidence",
)


@dataclass(frozen=True)
class AutoresolveOutcome:
    """Result of :func:`maybe_autoresolve_lifecycle_case`."""

    called_api: bool
    """True if confidence was above threshold and an HTTP request was sent."""

    http_status: int | None
    response_json: dict[str, Any] | None
    skipped_reason: str | None
    """Set when no request was sent (e.g. low confidence)."""


def extract_shadow_autoresolve_confidence(shadow_data: dict[str, Any]) -> float | None:
    """Resolve a normalized ``[0, 1]`` confidence score from a Shadow analyze payload."""
    metrics = shadow_data.get("confidence_metrics")
    if isinstance(metrics, dict):
        for key in _CONFIDENCE_METRIC_KEYS:
            raw = metrics.get(key)
            if raw is None:
                continue
            try:
                val = float(raw)
            except TypeError, ValueError:
                continue
            if 0.0 <= val <= 1.0:
                return val
        p_fraud = metrics.get("p_fraud")
        if p_fraud is not None:
            try:
                return max(0.0, min(1.0, 1.0 - float(p_fraud)))
            except TypeError, ValueError:
                pass
    try:
        risk = float(shadow_data.get("risk_score", 0.0))
    except TypeError, ValueError:
        return None
    return max(0.0, min(1.0, 1.0 - risk / 100.0))


def shadow_recommends_autoresolve(shadow_data: dict[str, Any]) -> bool:
    """True when Shadow structural output indicates a machine-safe auto-clear disposition."""
    if bool(shadow_data.get("is_fraud")):
        return False
    metrics = shadow_data.get("confidence_metrics")
    if isinstance(metrics, dict):
        if metrics.get("auto_resolve") is True or metrics.get("recommend_auto_resolve") is True:
            return True
        for key in ("recommended_action", "disposition", "recommended_disposition"):
            raw = metrics.get(key)
            if raw is None:
                continue
            token = str(raw).strip().upper()
            if token in _AUTO_RESOLVE_RECOMMENDATIONS:
                return True
    try:
        risk = float(shadow_data.get("risk_score", 100.0))
    except TypeError, ValueError:
        return False
    return risk <= 25.0 and not bool(shadow_data.get("is_fraud"))


def shadow_autoresolve_eligible(
    shadow_data: dict[str, Any],
) -> tuple[bool, float | None, str | None]:
    """
    Return ``(eligible, confidence, skip_reason)`` for autonomous ``RESOLVED_AUTO`` transitions.
    """
    confidence = extract_shadow_autoresolve_confidence(shadow_data)
    if confidence is None or not (confidence > CONFIDENCE_THRESHOLD):
        return False, confidence, "confidence_not_above_threshold"
    if not shadow_recommends_autoresolve(shadow_data):
        return False, confidence, "shadow_does_not_recommend_autoresolve"
    return True, confidence, None


def build_autoresolve_reason_code(shadow_data: dict[str, Any]) -> str:
    """Compact reason code for ``case_history`` (128 char column cap)."""
    base = DEFAULT_REASON_CODE
    metrics = shadow_data.get("confidence_metrics")
    disposition: str | None = None
    if isinstance(metrics, dict):
        for key in ("recommended_action", "disposition", "recommended_disposition"):
            raw = metrics.get(key)
            if raw is not None and str(raw).strip():
                disposition = str(raw).strip().upper()
                break
    if disposition:
        candidate = f"{base}:{disposition}"
        return candidate[:128]
    return base[:128]


def build_autoresolve_agent_notes(
    shadow_data: dict[str, Any],
    *,
    confidence: float | None,
) -> str:
    """Forensic narrative stored on the transition ``audit_logs.agent_notes`` row."""
    payload: dict[str, Any] = {
        "source": "shadow_autoresolve",
        "confidence": confidence,
        "risk_score": shadow_data.get("risk_score"),
        "is_fraud": shadow_data.get("is_fraud"),
        "reasoning": shadow_data.get("reasoning"),
        "confidence_metrics": shadow_data.get("confidence_metrics"),
        "ai_reasoning": shadow_data.get("ai_reasoning"),
    }
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False, default=str)[:32768]


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
