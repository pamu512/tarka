"""FastAPI ingestion gateway: rule engine first, then conditional Shadow AI analyze."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from ingestor.manifest_schema import TransactionSchema

logger = logging.getLogger(__name__)

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
        title="tarka-orchestrator",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.state.rule_engine_url = rule_base
    application.state.shadow_agent_url = shadow_base or None
    application.state.shadow_api_key = shadow_key
    application.state.shadow_analyze_timeout_seconds = shadow_deadline_s

    @application.post("/v1/ingest")
    async def v1_ingest(
        transaction: TransactionSchema,
        request: Request,
    ) -> dict[str, Any]:
        """
        Call the rule engine ``/v1/evaluate`` first.

        If (and only if) the rule engine includes ``SHADOW_REVIEW`` in ``actions``, POST the same
        transaction payload to the Shadow sidecar ``/v1/analyze``. Outcomes that are only
        ``BLOCK``, ``ALLOW``, ``FLAG``, etc. skip the Shadow hop to conserve downstream compute.
        """
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
        elif "SHADOW_REVIEW" in actions and shadow_base_st:
            out["orchestrator_fallback_decision"] = "FLAG"
            out["orchestrator_fallback_reason"] = "shadow_analyze_deadline_exceeded"
            out["orchestrator_shadow_deadline_seconds"] = shadow_read_s
        return out

    return application


app = create_app()
