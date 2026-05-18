"""Shared rule-engine + Shadow + audit persistence path for transaction envelopes."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from fastapi import BackgroundTasks, HTTPException, Request, status
from ingestor.manifest_schema import TransactionSchema

from orchestrator.audit_case_worker import (
    TRIGGER_ACTIONS_FOR_LIFECYCLE,
    persist_orchestrator_audit_log,
)
from orchestrator.enforcement.log_decision import persist_lekh_decision
from orchestrator.queues.shadow_dispatch import dispatch_shadow_investigate_if_review
from orchestrator.shadow_graph_payload import build_shadow_analyze_payload
from orchestrator.shadow_hypothesis_audit import evaluate_transaction_shadow_matches

logger = logging.getLogger(__name__)


def actions_from_rule_payload(rule_data: dict[str, Any]) -> list[str]:
    raw = rule_data.get("actions")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "rule_engine_invalid_actions_shape", "actions": raw},
        )
    return [str(a) for a in raw]


async def execute_transaction_ingest(
    *,
    request: Request,
    background_tasks: BackgroundTasks,
    transaction: TransactionSchema,
) -> dict[str, Any]:
    """Run ``/v1/ingest`` policy + optional Shadow + durable audit rows for one envelope."""
    payload = transaction.model_dump(mode="json")
    tid = str(transaction.entity_id)
    rule_url = f"{request.app.state.rule_engine_url}/v1/evaluate"
    rule_timeout = httpx.Timeout(30.0, connect=10.0)
    shadow_read_s = float(request.app.state.shadow_analyze_timeout_seconds)
    shadow_http_timeout = httpx.Timeout(shadow_read_s, connect=min(5.0, shadow_read_s))
    shadow_base_st: str | None = request.app.state.shadow_agent_url
    shadow_key_st: str | None = request.app.state.shadow_api_key
    actions: list[str] = []

    gc = getattr(request.app.state, "graph_client", None)
    analytics = getattr(request.app.state, "analytics", None)

    async def _ingest_graph() -> None:
        if gc is None:
            return
        try:
            await gc.ingest_transaction(transaction)
        except Exception:
            logger.exception("orchestrator_graph_ingest_failed transaction_id=%s", tid)

    async def _append_analytics() -> None:
        if analytics is None:
            return
        try:
            await asyncio.to_thread(analytics.append_transaction, transaction)
        except Exception:
            logger.exception("orchestrator_analytics_append_failed transaction_id=%s", tid)

    async def _ingest_sidecars_gather() -> None:
        await asyncio.gather(_ingest_graph(), _append_analytics())

    try:
        async with httpx.AsyncClient(timeout=rule_timeout) as client:
            rule_response = await client.post(rule_url, json=payload)
            rule_response.raise_for_status()
            rule_data = rule_response.json()

            actions = actions_from_rule_payload(rule_data)
            sdn_client = getattr(request.app.state, "shadow_dispatch_nats", None)
            try:
                await dispatch_shadow_investigate_if_review(
                    sdn_client,
                    entity_id=tid,
                    metadata=dict(transaction.metadata),
                    rule_data=rule_data,
                    actions=actions,
                )
            except Exception:
                logger.exception(
                    "orchestrator_shadow_dispatch_nats_publish_failed transaction_id=%s",
                    tid,
                )
            shadow_data: dict[str, Any] | None = None
            shadow_fallback_reason: str | None = None

            if "SHADOW_REVIEW" in actions:
                await _ingest_sidecars_gather()
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
                    shadow_body = await build_shadow_analyze_payload(transaction, gc)
                    shadow_resp = await client.post(
                        analyze_url,
                        json=shadow_body,
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
                    logger.warning(
                        "orchestrator_shadow_sidecar_unreachable url=%s transaction_id=%s exc=%s",
                        analyze_url,
                        tid,
                        exc,
                    )
                    shadow_data = None
                    shadow_fallback_reason = "SIDECAR_UNREACHABLE"
            else:
                background_tasks.add_task(_ingest_sidecars_gather)
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

    shadow_matches: list[dict[str, Any]] = []
    try:
        shadow_matches = await evaluate_transaction_shadow_matches(request.app.state, transaction)
    except Exception:
        logger.exception("orchestrator_shadow_hypothesis_eval_failed transaction_id=%s", tid)

    fac = getattr(request.app.state, "audit_session_factory", None)
    if fac is not None:
        try:
            async with fac() as session:
                async with session.begin():
                    await persist_lekh_decision(session, entity_id=tid, rule_data=rule_data)
                    await persist_orchestrator_audit_log(
                        session,
                        entity_id=tid,
                        metadata=dict(transaction.metadata),
                        actions=actions,
                        rule_data=rule_data,
                        shadow_data=shadow_data,
                        shadow_matches=shadow_matches,
                    )
        except Exception:
            logger.exception(
                "orchestrator_lekh_or_audit_persist_failed transaction_id=%s",
                tid,
            )

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
