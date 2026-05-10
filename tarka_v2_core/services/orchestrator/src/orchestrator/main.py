"""FastAPI ingestion gateway: rule engine first, then conditional Shadow AI analyze."""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from ingestor.manifest_schema import TransactionSchema

from orchestrator.openapi_schemas import (
    BadGateway502,
    DemoSimulateResponse,
    HTTPValidationError422,
    HealthFullResponse,
    IngestResponse,
    ServiceUnavailable503,
)

logger = logging.getLogger(__name__)

_ORCHESTRATOR_DESCRIPTION = """\
Public gateway for submitting **transaction envelopes** and retrieving combined outcomes.

## Transaction body (`TransactionSchema`)

All ingestion requests must provide:

| Field | Requirement |
|-------|-------------|
| **entity_id** | UUID identifying the transaction |
| **amount** | Finite number strictly greater than zero |
| **timestamp** | ISO 8601 datetime |
| **metadata** | JSON object (optional; default `{}`). Arbitrary keys allowed **inside** `metadata` only. |

The top-level JSON object **must not** include fields other than these four (`extra` is forbidden). \
Unknown keys at the root are rejected with **422** validation errors.

## Behavior overview

1. The orchestrator forwards your envelope to the policy tier and returns its structured outcome.
2. If that outcome requests secondary fraud review, the orchestrator may invoke an analysis tier \
and merge its structured result when available.

Responses never embed internal service URLs or hop-by-hop routing configuration.
"""

_ORCHESTRATOR_TAGS: list[dict[str, str]] = [
    {
        "name": "Ingestion",
        "description": (
            "Submit canonical transaction envelopes. Responses combine rule outcomes with "
            "optional secondary analysis when policy requests it."
        ),
    },
    {
        "name": "Operations",
        "description": "Readiness and dependency probes for orchestration and dashboards.",
    },
    {
        "name": "Demo",
        "description": "Non-production helpers for UI simulations.",
    },
]

_RESP_422 = {
    422: {
        "model": HTTPValidationError422,
        "description": (
            "Request body failed validation: missing required fields, invalid types, "
            "non-finite amount, or extra top-level keys on the transaction envelope."
        ),
    },
}

_RESP_INGEST = {
    **_RESP_422,
    502: {
        "model": BadGateway502,
        "description": "An upstream tier returned an HTTP error or an unexpected payload shape.",
    },
    503: {
        "model": ServiceUnavailable503,
        "description": (
            "The gateway could not reach an upstream tier, or secondary analysis was required "
            "but not configured on this deployment."
        ),
    },
}

_DEFAULT_RULE_ENGINE_URL = "http://127.0.0.1:8778"


def _rule_engine_base_url() -> str:
    return os.environ.get("RULE_ENGINE_URL", _DEFAULT_RULE_ENGINE_URL).rstrip("/")


def _shadow_agent_base_url() -> str:
    return os.environ.get("SHADOW_AGENT_URL", "").strip().rstrip("/")


def _shadow_api_key() -> str | None:
    raw = os.environ.get("SHADOW_API_KEY", "").strip()
    return raw or None


_DEFAULT_SHADOW_ANALYZE_TIMEOUT_S = 3.0


def _shadow_analyze_timeout_seconds(override: float | None) -> float:
    """Hard deadline for ``POST …/v1/analyze``; on expiry orchestrator returns a ``FLAG`` fallback."""
    if override is not None:
        return max(0.05, float(override))
    raw = os.environ.get("ORCHESTRATOR_SHADOW_ANALYZE_TIMEOUT_SECONDS", "").strip()
    if raw:
        return max(0.05, float(raw))
    return _DEFAULT_SHADOW_ANALYZE_TIMEOUT_S


def _actions_from_rule_payload(rule_data: dict[str, Any]) -> list[str]:
    raw = rule_data.get("actions")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "rule_engine_invalid_actions_shape", "actions": raw},
        )
    return [str(a) for a in raw]


def create_app(
    *,
    rule_engine_url: str | None = None,
    shadow_agent_url: str | None = None,
    shadow_api_key: str | None = None,
    shadow_analyze_timeout_seconds: float | None = None,
) -> FastAPI:
    """
    Build the ASGI app.

    Parameters:
        rule_engine_url: Override rule engine base URL (tests).
        shadow_agent_url: Override Shadow sidecar base URL (tests); falls back to :envvar:`SHADOW_AGENT_URL`.
        shadow_api_key: Override ``X-Shadow-Token`` (tests); falls back to :envvar:`SHADOW_API_KEY`.
        shadow_analyze_timeout_seconds: Override Shadow ``/v1/analyze`` read deadline (tests);
            falls back to :envvar:`ORCHESTRATOR_SHADOW_ANALYZE_TIMEOUT_SECONDS` or **3s**.
    """
    rule_base = (rule_engine_url or _rule_engine_base_url()).rstrip("/")
    shadow_base = (
        shadow_agent_url if shadow_agent_url is not None else _shadow_agent_base_url()
    ).rstrip("/")
    shadow_key = shadow_api_key if shadow_api_key is not None else _shadow_api_key()
    shadow_deadline_s = _shadow_analyze_timeout_seconds(shadow_analyze_timeout_seconds)

    application = FastAPI(
        title="Tarka Orchestrator API",
        description=_ORCHESTRATOR_DESCRIPTION,
        version="0.1.0",
        docs_url=None,
        redoc_url="/docs",
        openapi_url="/openapi.json",
        openapi_tags=_ORCHESTRATOR_TAGS,
    )
    application.state.rule_engine_url = rule_base
    application.state.shadow_agent_url = shadow_base or None
    application.state.shadow_api_key = shadow_key
    application.state.shadow_analyze_timeout_seconds = shadow_deadline_s

    @application.post(
        "/v1/ingest",
        tags=["Ingestion"],
        summary="Ingest a transaction",
        description=(
            "Accepts a **TransactionSchema** JSON body. The orchestrator evaluates policy first; "
            "if the outcome requests secondary fraud review, it may run an additional analysis step "
            "and merge that structured result. Pure allow/block/flag outcomes do not trigger that "
            "extra step."
        ),
        response_model=IngestResponse,
        responses=_RESP_INGEST,
        response_model_exclude_none=True,
    )
    async def v1_ingest(
        transaction: TransactionSchema,
        request: Request,
    ) -> dict[str, Any]:
        """Evaluate policy for the given transaction envelope and optionally attach analysis output."""
        payload = transaction.model_dump(mode="json")
        tid = str(transaction.entity_id)
        rule_url = f"{request.app.state.rule_engine_url}/v1/evaluate"
        rule_timeout = httpx.Timeout(30.0, connect=10.0)
        shadow_read_s = float(request.app.state.shadow_analyze_timeout_seconds)
        shadow_http_timeout = httpx.Timeout(shadow_read_s, connect=min(5.0, shadow_read_s))
        shadow_base_st: str | None = request.app.state.shadow_agent_url
        shadow_key_st: str | None = request.app.state.shadow_api_key
        actions: list[str] = []

        try:
            async with httpx.AsyncClient(timeout=rule_timeout) as client:
                rule_response = await client.post(rule_url, json=payload)
                rule_response.raise_for_status()
                rule_data = rule_response.json()

                actions = _actions_from_rule_payload(rule_data)
                shadow_data: dict[str, Any] | None = None
                shadow_fallback_reason: str | None = None

                if "SHADOW_REVIEW" in actions:
                    if not shadow_base_st:
                        raise HTTPException(
                            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="shadow_agent_url_required_when_rule_engine_requests_shadow_review",
                        )
                    analyze_url = f"{shadow_base_st}/v1/analyze"
                    headers: dict[str, str] = {}
                    if shadow_key_st:
                        headers["X-Shadow-Token"] = shadow_key_st
                    logger.info(
                        "orchestrator_shadow_downstream_post url=%s transaction_id=%s actions=%s",
                        analyze_url,
                        tid,
                        actions,
                    )
                    try:
                        shadow_resp = await client.post(
                            analyze_url,
                            json=payload,
                            headers=headers or None,
                            timeout=shadow_http_timeout,
                        )
                        shadow_resp.raise_for_status()
                        shadow_data = shadow_resp.json()
                    except httpx.TimeoutException as exc:
                        logger.warning(
                            "orchestrator_shadow_analyze_deadline_exceeded url=%s transaction_id=%s "
                            "deadline_s=%s exc=%s",
                            analyze_url,
                            tid,
                            shadow_read_s,
                            exc,
                        )
                        shadow_data = None
                        shadow_fallback_reason = "shadow_analyze_deadline_exceeded"
                    except httpx.RequestError as exc:
                        # ``TimeoutException`` is handled above; remaining ``RequestError`` subclasses
                        # cover refused connections, resets, TLS/DNS failures, etc. (dead-letter path).
                        logger.warning(
                            "orchestrator_shadow_sidecar_unreachable url=%s transaction_id=%s exc=%s",
                            analyze_url,
                            tid,
                            exc,
                        )
                        shadow_data = None
                        shadow_fallback_reason = "SIDECAR_UNREACHABLE"
                else:
                    logger.info(
                        "orchestrator_shadow_skipped transaction_id=%s actions=%s",
                        tid,
                        actions,
                    )

        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "error": "upstream_http_error",
                    "url": str(exc.request.url),
                    "status_code": exc.response.status_code,
                    "body": exc.response.text[:4096],
                },
            ) from exc
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error": "upstream_unreachable", "message": str(exc)},
            ) from exc

        out: dict[str, Any] = {
            "rule_engine": rule_data,
            "transaction_id": tid,
        }
        if shadow_data is not None:
            out["shadow_agent"] = shadow_data
        elif "SHADOW_REVIEW" in actions and shadow_base_st and shadow_fallback_reason:
            out["orchestrator_fallback_decision"] = "FLAG"
            out["orchestrator_fallback_reason"] = shadow_fallback_reason
            if shadow_fallback_reason == "shadow_analyze_deadline_exceeded":
                out["orchestrator_shadow_deadline_seconds"] = shadow_read_s
        return out

    @application.get(
        "/health/full",
        tags=["Operations"],
        summary="Aggregate health matrix",
        description=(
            "Returns a single JSON snapshot with local process status and HTTP probes against "
            "configured upstream dependencies (policy tier health endpoint and analysis tier DB health "
            "when configured). Intended for load balancers and ops dashboards."
        ),
        response_model=HealthFullResponse,
    )
    async def health_full(request: Request) -> dict[str, Any]:
        """Aggregate readiness across this process and configured backends."""
        rule_base: str = request.app.state.rule_engine_url
        shadow_base: str | None = request.app.state.shadow_agent_url
        shadow_key: str | None = request.app.state.shadow_api_key
        timeout = httpx.Timeout(5.0, connect=3.0)

        services: list[dict[str, Any]] = [
            {
                "component": "orchestrator",
                "status": "ok",
                "latency_ms": 0.0,
                "detail": "process handling request",
            }
        ]

        async with httpx.AsyncClient(timeout=timeout) as client:
            t0 = time.perf_counter()
            try:
                r = await client.get(f"{rule_base}/health")
                dt_ms = (time.perf_counter() - t0) * 1000.0
                if r.status_code == 200:
                    services.append(
                        {
                            "component": "rule_engine",
                            "status": "ok",
                            "latency_ms": round(dt_ms, 2),
                            "detail": f"HTTP {r.status_code}",
                        }
                    )
                else:
                    services.append(
                        {
                            "component": "rule_engine",
                            "status": "degraded",
                            "latency_ms": round(dt_ms, 2),
                            "detail": f"HTTP {r.status_code}",
                        }
                    )
            except httpx.RequestError as exc:
                services.append(
                    {
                        "component": "rule_engine",
                        "status": "offline",
                        "latency_ms": None,
                        "detail": str(exc),
                    }
                )

            if not shadow_base:
                services.append(
                    {
                        "component": "shadow_agent",
                        "status": "not_configured",
                        "latency_ms": None,
                        "detail": "SHADOW_AGENT_URL unset on orchestrator",
                    }
                )
            else:
                headers: dict[str, str] = {}
                if shadow_key:
                    headers["X-Shadow-Token"] = shadow_key
                t1 = time.perf_counter()
                try:
                    r2 = await client.get(
                        f"{shadow_base}/health/db",
                        headers=headers or None,
                    )
                    dt2 = (time.perf_counter() - t1) * 1000.0
                    if r2.status_code == 200:
                        services.append(
                            {
                                "component": "shadow_agent",
                                "status": "ok",
                                "latency_ms": round(dt2, 2),
                                "detail": f"HTTP {r2.status_code}",
                            }
                        )
                    else:
                        services.append(
                            {
                                "component": "shadow_agent",
                                "status": "degraded",
                                "latency_ms": round(dt2, 2),
                                "detail": f"HTTP {r2.status_code}",
                            }
                        )
                except httpx.RequestError as exc:
                    services.append(
                        {
                            "component": "shadow_agent",
                            "status": "offline",
                            "latency_ms": None,
                            "detail": str(exc),
                        }
                    )

        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "services": services,
        }

    @application.post(
        "/v1/demo/simulate_attack",
        tags=["Demo"],
        summary="Simulate attack-pattern batch (demo)",
        description=(
            "Returns a fixed batch of synthetic rows for UI demos (integrity scores and verdict labels). "
            "Does not persist data or call upstream tiers."
        ),
        response_model=DemoSimulateResponse,
        responses=_RESP_422,
    )
    async def v1_demo_simulate_attack() -> dict[str, Any]:
        """Return a non-streaming batch of simulated results for UI triggers."""
        n = 5
        now = datetime.now(UTC)
        results: list[dict[str, Any]] = []
        for i in range(n):
            tid = str(uuid.uuid4())
            results.append(
                {
                    "pattern_index": i,
                    "total": n,
                    "transaction_id": tid,
                    "amount": round(50.0 + i * 12.5, 2),
                    "currency": "USD",
                    "channel": "card_not_present",
                    "shadow_verdict": "FLAG" if i % 2 == 0 else "ALLOW",
                    "integrity_confidence": round(min(0.98, 0.52 + i * 0.09), 3),
                    "simulated_at": now.isoformat(),
                },
            )
        return {"total": n, "results": results}

    return application


app = create_app()
