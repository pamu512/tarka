"""httpx System One client. One POST, no retries, no invented answers."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

import httpx

from jev_system_one.questions import (
    HAS_ENOUGH_SIGNAL,
    PACK_ID,
    PATTERN_HINT,
    PATTERN_HINT_OPTIONS,
    REVIEW_PRIORITY,
    REVIEW_PRIORITY_OPTIONS,
)


@dataclass(frozen=True)
class SystemOneJudgment:
    answers: dict[str, Any] | None
    latency_ms: int
    error: str | None


def systemone_endpoint(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/v1/systemone"):
        return base
    return base + "/v1/systemone"


def _confidence(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if value < 0 or value > 1:
        return None
    return float(value)


def _noul_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = value.strip().lower()
        if token == "yes":
            return True
        if token == "no":
            return False
    return None


def parse_systemone_response(payload: Any) -> dict[str, Any] | None:
    """Return normalized answers or None when the body is not the fixed schema.

    Does not fill missing answers. Free-text fields are ignored, never forwarded.
    """
    if not isinstance(payload, dict):
        return None
    raw_answers = payload.get("answers")
    if not isinstance(raw_answers, dict):
        return None
    signal = raw_answers.get(HAS_ENOUGH_SIGNAL)
    priority = raw_answers.get(REVIEW_PRIORITY)
    pattern = raw_answers.get(PATTERN_HINT)
    if not all(isinstance(item, dict) for item in (signal, priority, pattern)):
        return None
    signal_value = _noul_value(signal.get("value"))
    signal_confidence = _confidence(signal.get("confidence"))
    priority_value = priority.get("value")
    priority_confidence = _confidence(priority.get("confidence"))
    pattern_value = pattern.get("value")
    pattern_confidence = _confidence(pattern.get("confidence"))
    if signal_value is None or signal_confidence is None:
        return None
    if not isinstance(priority_value, str) or priority_value not in REVIEW_PRIORITY_OPTIONS:
        return None
    if priority_confidence is None:
        return None
    if not isinstance(pattern_value, str) or pattern_value not in PATTERN_HINT_OPTIONS:
        return None
    if pattern_confidence is None:
        return None
    if payload.get("pack_id") not in (None, PACK_ID):
        return None
    return {
        HAS_ENOUGH_SIGNAL: {"value": signal_value, "confidence": signal_confidence},
        REVIEW_PRIORITY: {"value": priority_value, "confidence": priority_confidence},
        PATTERN_HINT: {"value": pattern_value, "confidence": pattern_confidence},
    }


class SystemOneClient:
    """POST ``/v1/systemone``. Timeout and non-200 are errors; nothing is retried."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        timeout_ms: int = 400,
    ) -> None:
        self.base_url = (base_url or "").strip()
        self.api_key = api_key or ""
        self.timeout_ms = timeout_ms if timeout_ms > 0 else 400

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        key = self.api_key.strip()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    async def judge(self, body: dict[str, Any]) -> SystemOneJudgment:
        url = systemone_endpoint(self.base_url)
        if not url:
            return SystemOneJudgment(answers=None, latency_ms=0, error="unconfigured")
        timeout = httpx.Timeout(self.timeout_ms / 1000)
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                response = await client.post(url, json=body, headers=self._headers())
        except httpx.TimeoutException:
            return SystemOneJudgment(
                answers=None,
                latency_ms=_elapsed_ms(started),
                error="timeout",
            )
        except httpx.RequestError:
            return SystemOneJudgment(
                answers=None,
                latency_ms=_elapsed_ms(started),
                error="transport",
            )
        latency_ms = _elapsed_ms(started)
        if response.status_code in (401, 403):
            return SystemOneJudgment(answers=None, latency_ms=latency_ms, error="auth")
        if response.status_code != 200:
            return SystemOneJudgment(answers=None, latency_ms=latency_ms, error="http")
        try:
            payload = response.json()
        except ValueError:
            return SystemOneJudgment(answers=None, latency_ms=latency_ms, error="schema")
        answers = parse_systemone_response(payload)
        if answers is None:
            return SystemOneJudgment(answers=None, latency_ms=latency_ms, error="schema")
        return SystemOneJudgment(answers=answers, latency_ms=latency_ms, error=None)


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))
