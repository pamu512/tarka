"""Evaluate enrichment: graph entity-risk + feature-service snapshot (bound circuits)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import httpx

from decision_api.config import settings
from decision_api.evaluate.score import tag_hop_unconfigured
from decision_api.graph_risk_freshness import (
    evaluate_graph_risk_freshness,
    parse_freshness_policy_by_event,
)
from decision_api.schemas import EvaluateRequest
from decision_api.tenant_flags import tenant_flag_enabled
from circuit import CircuitOpenError

_rt: SimpleNamespace | None = None


def bind_runtime(
    *,
    circuit_graph: Any,
    circuit_feature: Any,
    metrics_inc: Any,
    upstream_headers: Any,
) -> None:
    """Wire circuit breakers / metrics from ``decision_api.main`` after they exist."""
    global _rt
    _rt = SimpleNamespace(
        circuit_graph=circuit_graph,
        circuit_feature=circuit_feature,
        metrics_inc=metrics_inc,
        upstream_headers=upstream_headers,
    )


def _require_rt() -> SimpleNamespace:
    if _rt is None:
        raise RuntimeError("evaluate enrichment runtime not bound")
    return _rt


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value) or asyncio.isfuture(value):
        return await value
    return value


def feature_snapshot_fallback(
    body: EvaluateRequest, redis_tag_list: list[str]
) -> dict[str, Any]:
    return {
        "tenant_id": body.tenant_id,
        "entity_id": body.entity_id,
        "event_type": body.event_type.value,
        "features": dict(body.payload),
        "redis_tags": redis_tag_list,
    }


async def fetch_feature_snapshot(
    http: httpx.AsyncClient, body: EvaluateRequest, redis_tag_list: list[str]
) -> dict[str, Any]:
    rt = _require_rt()
    if not settings.feature_service_url:
        return feature_snapshot_fallback(body, redis_tag_list)
    url = settings.feature_service_url.rstrip("/") + "/v1/snapshot"
    r = await http.post(
        url,
        json={
            "tenant_id": body.tenant_id,
            "entity_id": body.entity_id,
            "event_type": body.event_type.value,
            "payload": body.payload,
        },
        headers=rt.upstream_headers(),
        timeout=settings.eval_step_feature_snapshot_timeout_seconds,
    )
    await _maybe_await(r.raise_for_status())
    payload = await _maybe_await(r.json())
    return payload if isinstance(payload, dict) else {}


async def fetch_feature_snapshot_wrapped(
    http: httpx.AsyncClient,
    body: EvaluateRequest,
    redis_tag_list: list[str],
    degrade_tags: list[str],
    tenant_flags: dict[str, Any],
) -> dict[str, Any]:
    rt = _require_rt()
    if tenant_flag_enabled(tenant_flags, "disable_feature_service"):
        degrade_tags.append("enrichment:disabled_by_tenant")
        return feature_snapshot_fallback(body, redis_tag_list)
    if tag_hop_unconfigured(degrade_tags, "features"):
        return feature_snapshot_fallback(body, redis_tag_list)
    try:
        return await rt.circuit_feature.call(
            lambda: fetch_feature_snapshot(http, body, redis_tag_list)
        )
    except CircuitOpenError:
        rt.metrics_inc("tarka_circuit_open_total_feature")
        degrade_tags.append("enrichment:unavailable")
        return feature_snapshot_fallback(body, redis_tag_list)


async def fetch_graph_risk(
    http: httpx.AsyncClient,
    tenant_id: str,
    entity_id: str,
    graph_checkpoint: str | None = None,
) -> dict[str, Any] | None:
    if not settings.graph_service_url:
        return None
    url = settings.graph_service_url.rstrip("/") + "/v1/analytics/entity-risk"
    params: dict[str, Any] = {"tenant_id": tenant_id, "entity_id": entity_id}
    if graph_checkpoint:
        params["checkpoint"] = graph_checkpoint
    r = await http.get(
        url,
        params=params,
        timeout=settings.eval_step_graph_risk_timeout_seconds,
    )
    await _maybe_await(r.raise_for_status())
    data = await _maybe_await(r.json())
    if not isinstance(data, dict):
        return None
    return data


async def fetch_graph_risk_wrapped(
    http: httpx.AsyncClient,
    tenant_id: str,
    entity_id: str,
    degrade_tags: list[str],
    tenant_flags: dict[str, Any],
    graph_checkpoint: str | None = None,
    event_type: str | None = None,
) -> dict[str, Any] | None:
    rt = _require_rt()
    if tenant_flag_enabled(tenant_flags, "disable_graph"):
        degrade_tags.append("graph:disabled_by_tenant")
        return None
    if tag_hop_unconfigured(degrade_tags, "graph"):
        if "graph:missing" not in degrade_tags:
            degrade_tags.append("graph:missing")
        return None
    try:
        data = await rt.circuit_graph.call(
            lambda: fetch_graph_risk(http, tenant_id, entity_id, graph_checkpoint)
        )
    except CircuitOpenError:
        rt.metrics_inc("tarka_circuit_open_total_graph")
        degrade_tags.append("graph:unavailable")
        return None
    if not isinstance(data, dict):
        return None
    default_policy = settings.graph_risk_freshness_default_policy
    if default_policy not in ("warn", "skip", "fail_closed"):
        default_policy = "warn"
    result = evaluate_graph_risk_freshness(
        data,
        max_age_minutes=settings.graph_risk_max_age_minutes,
        tenant_id=tenant_id,
        entity_id=entity_id,
        event_type=event_type,
        default_policy=default_policy,  # type: ignore[arg-type]
        policy_by_event_type=parse_freshness_policy_by_event(
            settings.graph_risk_freshness_policy_by_event
        ),
        metrics_inc=rt.metrics_inc,
    )
    if result.action == "skip":
        if "graph:stale_skipped" not in degrade_tags:
            degrade_tags.append("graph:stale_skipped")
        return None
    if result.action == "fail_closed":
        if "graph:stale_fail_closed" not in degrade_tags:
            degrade_tags.append("graph:stale_fail_closed")
        return None
    return data


async def fetch_object_attention(
    http: httpx.AsyncClient,
    tenant_id: str,
    objects: list[dict[str, str]],
) -> list[dict[str, Any]]:
    if not settings.graph_service_url or not objects:
        return []
    rt = _require_rt()
    url = settings.graph_service_url.rstrip("/") + "/v1/objects/attention"
    r = await http.post(
        url,
        json={
            "tenant_id": tenant_id,
            "objects": [
                {
                    "external_id": o["external_id"],
                    "entity_type": o.get("entity_type") or "Custom",
                    "on_this_event": True,
                }
                for o in objects
                if o.get("external_id")
            ],
        },
        headers=rt.upstream_headers(),
        timeout=settings.eval_step_graph_risk_timeout_seconds,
    )
    await _maybe_await(r.raise_for_status())
    data = await _maybe_await(r.json())
    if not isinstance(data, dict):
        return []
    rows = data.get("attention")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


async def fetch_object_attention_wrapped(
    http: httpx.AsyncClient,
    tenant_id: str,
    objects: list[dict[str, str]],
    degrade_tags: list[str],
    tenant_flags: dict[str, Any],
) -> list[dict[str, Any]]:
    """Fail-soft. Empty list means pack does not attend."""
    rt = _require_rt()
    if tenant_flag_enabled(tenant_flags, "disable_graph"):
        return []
    if tag_hop_unconfigured(degrade_tags, "graph"):
        return []
    try:
        return await rt.circuit_graph.call(
            lambda: fetch_object_attention(http, tenant_id, objects)
        )
    except CircuitOpenError:
        rt.metrics_inc("tarka_circuit_open_total_graph")
        if "graph:unavailable" not in degrade_tags:
            degrade_tags.append("graph:unavailable")
        return []
    except Exception:
        if "graph:unavailable" not in degrade_tags:
            degrade_tags.append("graph:unavailable")
        return []
