from typing import Any

import httpx

from decision_api.evaluate.score import tag_hop_unconfigured


def apply_opa_unconfigured(degrade_tags: list[str], opa_url: str) -> bool:
    """Tag ``opa:unconfigured`` when the hop URL is empty. Returns True if skipped."""
    return tag_hop_unconfigured(degrade_tags, "opa", opa_url)


async def evaluate_opa(
    http: httpx.AsyncClient,
    opa_url: str,
    input_payload: dict[str, Any],
    *,
    timeout_seconds: float = 2.0,
) -> dict[str, Any] | None:
    if not opa_url:
        return None
    url = opa_url.rstrip("/") + "/v1/data/fraud/result"
    try:
        r = await http.post(url, json={"input": input_payload}, timeout=timeout_seconds)
        if r.status_code != 200:
            return None
        data = r.json()
        return data.get("result")
    except httpx.HTTPError:
        return None


async def evaluate_opa_or_raise(
    http: httpx.AsyncClient,
    opa_url: str,
    input_payload: dict[str, Any],
    *,
    timeout_seconds: float = 2.0,
) -> dict[str, Any] | None:
    """Strict variant for circuit breaker: raises on transport/HTTP errors; returns result or None body."""
    if not opa_url:
        return None
    url = opa_url.rstrip("/") + "/v1/data/fraud/result"
    r = await http.post(url, json={"input": input_payload}, timeout=timeout_seconds)
    r.raise_for_status()
    data = r.json()
    return data.get("result")
