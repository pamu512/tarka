"""DecisionOutcomeHandler — single post-decision act path (Phase 0).

Consolidates: decision log emit, challenge webhook, enforcement adapters,
metrics, WS broadcast, NATS/local publish, optional case create for deny/review.
"""

from __future__ import annotations

import inspect
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

from decision_api.enforcement import (
    apply_enforcement_adapters,
    resolve_enforcement_action,
)

log = logging.getLogger("decision-api.outcome")

MetricsInc = Callable[..., Any]
BgAddTask = Callable[..., Any]


def wrap_outcome_task(fn: Callable[..., Any], metrics_inc: MetricsInc) -> Callable[..., Any]:
    """Preserve ``fn.__name__``; log + metric if the background side effect fails."""
    name = getattr(fn, "__name__", "outcome")

    async def _run(*args: Any, **kwargs: Any) -> None:
        try:
            result = fn(*args, **kwargs)
            if inspect.isawaitable(result):
                await result
        except Exception:
            log.exception("decision_outcome_failed task=%s", name)
            try:
                metrics_inc(f"tarka_decision_outcome_failed_{name}_total")
            except Exception:
                pass

    _run.__name__ = name
    return _run


@dataclass
class DecisionOutcomeContext:
    """Inputs for post-evaluate side effects."""

    trace_id: str
    tenant_id: str
    entity_id: str
    event_type: str
    decision: str
    score: float
    tags: list[str]
    rule_hits: list[str] = field(default_factory=list)
    signal_tags: list[str] = field(default_factory=list)
    ml_score: float | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    recommended_action: str | None = None
    challenge_metadata: dict[str, Any] | None = None
    fallback_reason: str | None = None
    decision_log_record: dict[str, Any] | None = None
    degrade_tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] | None = None
    # Production shadow duplicate: skip mutating side effects (graph, challenge, cases).
    shadow_request: bool = False


def schedule_decision_outcomes(
    bg: Any,
    *,
    ctx: DecisionOutcomeContext,
    http: Any,
    app_state: Any,
    emit_decision_log: Callable[[dict[str, Any]], Awaitable[Any]],
    maybe_dispatch_challenge_webhook: Callable[..., Awaitable[Any]],
    broadcast_decision: Callable[[dict[str, Any]], Awaitable[Any]],
    publish_decision: Callable[..., Awaitable[Any]],
    metrics_inc: MetricsInc,
    case_api_url: str = "",
    case_create_on_deny_review: bool = False,
    integration_ingress_url: str = "",
    ingress_internal_token: str = "",
    loyalty_abuse_url: str = "",
    loyalty_abuse_api_key: str = "",
    upstream_headers: dict[str, str] | None = None,
    graph_upsert: Callable[..., Awaitable[Any]] | None = None,
    graph_upsert_args: tuple[Any, ...] = (),
    shadow_evaluation: Callable[..., Awaitable[Any]] | None = None,
    shadow_args: tuple[Any, ...] = (),
) -> None:
    """Enqueue all post-decision side effects onto a FastAPI BackgroundTasks-like object."""

    def add(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        bg.add_task(wrap_outcome_task(fn, metrics_inc), *args, **kwargs)

    if ctx.decision_log_record is not None:
        add(emit_decision_log, ctx.decision_log_record)

    if not ctx.shadow_request and graph_upsert is not None:
        add(graph_upsert, *graph_upsert_args)

    if not ctx.shadow_request:
        add(
            maybe_dispatch_challenge_webhook,
            http=http,
            trace_id=ctx.trace_id,
            tenant_id=ctx.tenant_id,
            entity_id=ctx.entity_id,
            decision=ctx.decision,
            recommended_action=ctx.recommended_action,
            challenge_metadata=ctx.challenge_metadata
            if isinstance(ctx.challenge_metadata, dict)
            else None,
        )

    _emit_decision_metrics(ctx, metrics_inc)

    from decision_api.degraded_decision_metrics import record_degraded_decision_metrics

    record_degraded_decision_metrics(
        ctx.degrade_tags,
        metrics_inc=metrics_inc,
        trace_id=ctx.trace_id,
    )

    enforcement_action = resolve_enforcement_action(
        ctx.decision, ctx.recommended_action
    )

    if not ctx.shadow_request:
        add(
            apply_enforcement_adapters,
            http=http,
            trace_id=ctx.trace_id,
            tenant_id=ctx.tenant_id,
            entity_id=ctx.entity_id,
            event_type=ctx.event_type,
            decision=ctx.decision,
            score=ctx.score,
            tags=ctx.tags,
            recommended_action=ctx.recommended_action,
            challenge_metadata=ctx.challenge_metadata
            if isinstance(ctx.challenge_metadata, dict)
            else None,
            metrics_inc=metrics_inc,
        )

    add(
        broadcast_decision,
        {
            "trace_id": ctx.trace_id,
            "tenant_id": ctx.tenant_id,
            "entity_id": ctx.entity_id,
            "event_type": ctx.event_type,
            "decision": ctx.decision,
            "score": ctx.score,
            "tags": ctx.tags,
            "enforcement_action": enforcement_action,
        },
    )

    add(
        publish_decision,
        app_state,
        {
            "trace_id": ctx.trace_id,
            "tenant_id": ctx.tenant_id,
            "entity_id": ctx.entity_id,
            "event_type": ctx.event_type,
            "decision": ctx.decision,
            "score": ctx.score,
            "tags": ctx.tags,
            "rule_hits": ctx.rule_hits,
            "signal_tags": ctx.signal_tags,
            "ml_score": ctx.ml_score,
            "payload": ctx.payload,
            "enforcement_action": enforcement_action,
            "recommended_action": ctx.recommended_action,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    if shadow_evaluation is not None:
        add(shadow_evaluation, *shadow_args)

    if (
        not ctx.shadow_request
        and case_create_on_deny_review
        and ctx.decision in ("deny", "review")
    ):
        add(
            maybe_create_case_for_outcome,
            http=http,
            case_api_url=case_api_url,
            ctx=ctx,
            headers=upstream_headers or {},
        )

    if not ctx.shadow_request:
        from decision_api.payout_hold_bridge import (
            maybe_create_payout_hold_from_evaluate,
            should_create_payout_hold,
        )

        meta = ctx.metadata if isinstance(ctx.metadata, dict) else None
        if should_create_payout_hold(
            metadata=meta, tags=ctx.tags, event_type=ctx.event_type
        ):
            add(
                maybe_create_payout_hold_from_evaluate,
                http=http,
                integration_ingress_url=integration_ingress_url,
                ingress_internal_token=ingress_internal_token,
                tenant_id=ctx.tenant_id,
                entity_id=ctx.entity_id,
                tags=ctx.tags,
                metadata=meta,
                trace_id=ctx.trace_id,
                event_type=ctx.event_type,
                metrics_inc=metrics_inc,
            )

    # Loyalty redeem bridge runs synchronously in evaluate/pipeline so
    # loyalty:friction:* tags land on the EvaluateResponse + audit record.

    if not ctx.shadow_request:
        from decision_api.promo_redemption_bridge import (
            maybe_record_promo_redemption_from_evaluate,
            should_record_promo_redemption,
        )

        meta = ctx.metadata if isinstance(ctx.metadata, dict) else None
        if should_record_promo_redemption(
            metadata=meta, tags=ctx.tags, event_type=ctx.event_type
        ):
            add(
                maybe_record_promo_redemption_from_evaluate,
                http=http,
                integration_ingress_url=integration_ingress_url,
                ingress_internal_token=ingress_internal_token,
                tenant_id=ctx.tenant_id,
                entity_id=ctx.entity_id,
                tags=ctx.tags,
                metadata=meta,
                payload=ctx.payload if isinstance(ctx.payload, dict) else None,
                trace_id=ctx.trace_id,
                event_type=ctx.event_type,
                metrics_inc=metrics_inc,
            )

    if not ctx.shadow_request:
        from decision_api.seller_integrity_bridge import (
            maybe_record_seller_integrity_from_evaluate,
            should_record_seller_integrity,
        )

        meta = ctx.metadata if isinstance(ctx.metadata, dict) else None
        if should_record_seller_integrity(metadata=meta, event_type=ctx.event_type):
            add(
                maybe_record_seller_integrity_from_evaluate,
                http=http,
                integration_ingress_url=integration_ingress_url,
                ingress_internal_token=ingress_internal_token,
                tenant_id=ctx.tenant_id,
                metadata=meta,
                payload=ctx.payload if isinstance(ctx.payload, dict) else None,
                trace_id=ctx.trace_id,
                event_type=ctx.event_type,
                metrics_inc=metrics_inc,
            )


def _emit_decision_metrics(
    ctx: DecisionOutcomeContext, metrics_inc: MetricsInc
) -> None:
    try:
        metrics_inc(f"fraud_decisions_{ctx.decision}_total", trace_id=ctx.trace_id)
        metrics_inc("fraud_evaluations_total", trace_id=ctx.trace_id)
        if ctx.fallback_reason:
            metrics_inc("fraud_fallback_total", trace_id=ctx.trace_id)
            reason_key = (
                re.sub(r"[^a-zA-Z0-9_]+", "_", str(ctx.fallback_reason))
                .strip("_")
                .lower()[:64]
            )
            if reason_key:
                metrics_inc(f"fraud_fallback_total_{reason_key}", trace_id=ctx.trace_id)
        for st in ctx.signal_tags:
            metrics_inc(f"fraud_signal_tag_{st}_total", trace_id=ctx.trace_id)
    except TypeError:
        metrics_inc(f"fraud_decisions_{ctx.decision}_total")
        metrics_inc("fraud_evaluations_total")


async def maybe_create_case_for_outcome(
    *,
    http: Any,
    case_api_url: str,
    ctx: DecisionOutcomeContext,
    headers: dict[str, str],
) -> None:
    """Best-effort case create for deny/review when case_api_url is configured."""
    base = (case_api_url or "").strip().rstrip("/")
    if not base:
        return
    priority = "high" if ctx.decision == "deny" else "medium"
    body = {
        "tenant_id": ctx.tenant_id,
        "title": f"Auto: {ctx.decision} {ctx.event_type} {ctx.entity_id}",
        "entity_id": ctx.entity_id,
        "trace_id": ctx.trace_id,
        "priority": priority,
    }
    try:
        r = await http.post(f"{base}/v1/cases", json=body, headers=headers, timeout=5.0)
        status = getattr(r, "status_code", None)
        if status is not None and int(status) >= 400:
            log.warning(
                "case_create_failed status=%s tenant_id=%s trace_id=%s",
                status,
                ctx.tenant_id,
                ctx.trace_id,
            )
    except Exception:
        log.warning(
            "case_create_error tenant_id=%s trace_id=%s",
            ctx.tenant_id,
            ctx.trace_id,
            exc_info=True,
        )


def force_deny_from_degrade_tags(degrade_tags: list[str] | None) -> bool:
    """True when catalog/graph freshness policy requires fail-closed deny."""
    if not degrade_tags:
        return False
    return (
        "feature:catalog_fail_closed" in degrade_tags
        or "graph:stale_fail_closed" in degrade_tags
    )
