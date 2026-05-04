import asyncio
import hashlib
import hmac
import json as _json
import logging
import os
import re as _re
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
import nats
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_api.config import settings

try:
    from decision_api.config import dependency_resilience_policy_table
except ImportError:
    # Backward-compatible fallback for branches that have main.py import but not the
    # config helper yet; keeps module importable during mixed revisions.
    def dependency_resilience_policy_table() -> dict[str, dict[str, float | int | str]]:
        return {
            "lists": {
                "timeout_seconds": settings.eval_step_list_timeout_seconds,
                "max_attempts": settings.eval_step_list_max_attempts,
                "circuit_failure_threshold": settings.circuit_list_failure_threshold,
                "circuit_recovery_seconds": settings.circuit_list_recovery_seconds,
                "on_failure": "SKIP",
            },
            "graph_risk": {
                "timeout_seconds": settings.eval_step_graph_risk_timeout_seconds,
                "max_attempts": settings.eval_step_graph_risk_max_attempts,
                "circuit_failure_threshold": settings.circuit_graph_failure_threshold,
                "circuit_recovery_seconds": settings.circuit_graph_recovery_seconds,
                "on_failure": "SKIP",
            },
            "feature_snapshot": {
                "timeout_seconds": settings.eval_step_feature_snapshot_timeout_seconds,
                "max_attempts": settings.eval_step_feature_snapshot_max_attempts,
                "circuit_failure_threshold": settings.circuit_feature_failure_threshold,
                "circuit_recovery_seconds": settings.circuit_feature_recovery_seconds,
                "on_failure": "SKIP",
            },
            "ml_score": {
                "timeout_seconds": settings.eval_step_ml_timeout_seconds,
                "max_attempts": settings.eval_step_ml_max_attempts,
                "circuit_failure_threshold": settings.circuit_ml_failure_threshold,
                "circuit_recovery_seconds": settings.circuit_ml_recovery_seconds,
                "on_failure": "SKIP",
            },
            "opa": {
                "timeout_seconds": settings.eval_step_opa_timeout_seconds,
                "max_attempts": settings.eval_step_opa_max_attempts,
                "circuit_failure_threshold": settings.circuit_opa_failure_threshold,
                "circuit_recovery_seconds": settings.circuit_opa_recovery_seconds,
                "on_failure": "SKIP",
            },
            "counter_snapshot": {
                "timeout_seconds": settings.eval_step_feature_snapshot_timeout_seconds,
                "max_attempts": settings.eval_step_feature_snapshot_max_attempts,
                "circuit_failure_threshold": settings.circuit_counter_failure_threshold,
                "circuit_recovery_seconds": settings.circuit_counter_recovery_seconds,
                "on_failure": "SKIP",
            },
            "location_eval": {
                "timeout_seconds": settings.eval_step_feature_snapshot_timeout_seconds,
                "max_attempts": settings.eval_step_feature_snapshot_max_attempts,
                "circuit_failure_threshold": settings.circuit_location_failure_threshold,
                "circuit_recovery_seconds": settings.circuit_location_recovery_seconds,
                "on_failure": "SKIP",
            },
            "calibration": {
                "timeout_seconds": settings.eval_step_feature_snapshot_timeout_seconds,
                "max_attempts": settings.eval_step_feature_snapshot_max_attempts,
                "circuit_failure_threshold": settings.circuit_calibration_failure_threshold,
                "circuit_recovery_seconds": settings.circuit_calibration_recovery_seconds,
                "on_failure": "SKIP",
            },
            "external_signals": {
                "timeout_seconds": settings.external_signal_timeout_seconds,
                "max_attempts": settings.eval_step_external_signal_max_attempts,
                "circuit_failure_threshold": settings.circuit_external_failure_threshold,
                "circuit_recovery_seconds": settings.circuit_external_recovery_seconds,
                "on_failure": "SKIP",
            },
            "graph_upsert": {
                "timeout_seconds": settings.eval_step_graph_upsert_timeout_seconds,
                "max_attempts": settings.eval_step_graph_upsert_max_attempts,
                "circuit_failure_threshold": settings.circuit_graph_failure_threshold,
                "circuit_recovery_seconds": settings.circuit_graph_recovery_seconds,
                "on_failure": "SKIP",
            },
        }


from decision_api.currency import normalize_amount
from decision_api.db import get_session, init_db
from decision_api.decision_log import build_decision_log_record, emit_decision_log
from decision_api.entity_link_store import entity_link_store
from decision_api.eval_dag import EvalDAGRuntime
from decision_api.eval_load_guard import EvalLoadGuard, acquire_eval_capacity
from decision_api.eval_steps import run_evaluation_step
from decision_api.external_signals import evaluate_external_signals
from decision_api.fingerprint_store import fingerprint_store
from decision_api.json_rules import (
    evaluate_json_rules,
    load_rules,
)
from decision_api.json_rules import (
    governance_summary as rules_governance_summary,
)
from decision_api.models import AuditRecord
from decision_api.opa_client import evaluate_opa_or_raise
from decision_api.redis_store import redis_tags
from decision_api.retention import DEFAULT_RETENTION_DAYS, retention_loop

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "shared"))
from circuit import AsyncCircuitBreaker, CircuitOpenError  # noqa: E402
from entity_lists import ListCheckResult, create_list_store  # noqa: E402
from event_time import event_time_unix_for_evaluate  # noqa: E402
from privacy import get_profile, mask_dict  # noqa: E402

from decision_api.aggregates import agg_store
from decision_api.attestation_taxonomy import attestation_signal_tags
from decision_api.challenge_policy import apply_challenge_policy, load_challenge_policies
from decision_api.consortium import consortium_score_delta, hash_entity_id
from decision_api.graph_decision_explanation import build_graph_decision_explanation_v1
from decision_api.graph_intel import graph_score_delta, graph_tags_from_risk
from decision_api.inference_build import (
    SCHEMA_VERSION as INFERENCE_SCHEMA_VERSION,
)
from decision_api.inference_build import (
    build_inference_context,
    derive_recommended_action,
)
from decision_api.integrity_policy import supplemental_tags_for_integrity
from decision_api.lists_api import get_store as _get_list_store
from decision_api.lists_api import router as lists_router
from decision_api.lists_api import set_store
from decision_api.location_context import merge_session_geo_from_device_and_features
from decision_api.policy_routing import (
    build_canary_cohort_audit,
    build_policy_routing_audit,
    cohort_bucket_0_99,
    decision_from_rule_score,
)
from decision_api.schemas import EvaluateRequest, EvaluateResponse
from decision_api.shadow import evaluate_shadow, load_shadow_rules, record_observation
from decision_api.tags import derive_contextual_tags
from decision_api.tenant_flags import tenant_flag_enabled
from decision_api.trusted_zones import load_trusted_zones_for_tenant
from decision_api.typology import evaluate_typologies, load_typology_definitions, reload_typology_definitions, summarize_typologies
from decision_api.typology_predicate_registry import load_predicate_registry, registry_public_view, reload_predicate_registry

# ---------- observability ----------
_shared_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "shared"))
if _shared_dir not in sys.path:
    sys.path.insert(0, _shared_dir)
from auth_rbac import require_role, setup_auth  # noqa: E402
from observability import get_metrics, setup_observability  # noqa: E402
from rate_limiter import setup_rate_limiter  # noqa: E402
from security_headers import setup_security_headers  # noqa: E402
from tenant_binding import parse_api_key_tenant_map  # noqa: E402

log = logging.getLogger("decision-api")


def _upstream_headers() -> dict[str, str]:
    """Shared auth headers for outbound service calls."""
    key = settings.upstream_api_key.strip() if settings.upstream_api_key.strip() else ""
    if not key:
        key = settings.api_keys.split(",")[0].strip() if settings.api_keys.strip() else ""
    return {"x-api-key": key} if key else {}


_circuit_graph = AsyncCircuitBreaker(
    "graph",
    failure_threshold=settings.circuit_graph_failure_threshold,
    recovery_seconds=settings.circuit_graph_recovery_seconds,
)
_circuit_feature = AsyncCircuitBreaker(
    "feature",
    failure_threshold=settings.circuit_feature_failure_threshold,
    recovery_seconds=settings.circuit_feature_recovery_seconds,
)
_circuit_ml = AsyncCircuitBreaker(
    "ml",
    failure_threshold=settings.circuit_ml_failure_threshold,
    recovery_seconds=settings.circuit_ml_recovery_seconds,
)
_circuit_opa = AsyncCircuitBreaker(
    "opa",
    failure_threshold=settings.circuit_opa_failure_threshold,
    recovery_seconds=settings.circuit_opa_recovery_seconds,
)
_circuit_list = AsyncCircuitBreaker(
    "list",
    failure_threshold=settings.circuit_list_failure_threshold,
    recovery_seconds=settings.circuit_list_recovery_seconds,
)
_circuit_calibration = AsyncCircuitBreaker(
    "calibration",
    failure_threshold=settings.circuit_calibration_failure_threshold,
    recovery_seconds=settings.circuit_calibration_recovery_seconds,
)
_circuit_counter = AsyncCircuitBreaker(
    "counter",
    failure_threshold=settings.circuit_counter_failure_threshold,
    recovery_seconds=settings.circuit_counter_recovery_seconds,
)
_circuit_location = AsyncCircuitBreaker(
    "location",
    failure_threshold=settings.circuit_location_failure_threshold,
    recovery_seconds=settings.circuit_location_recovery_seconds,
)
_circuit_external = AsyncCircuitBreaker(
    "external",
    failure_threshold=settings.circuit_external_failure_threshold,
    recovery_seconds=settings.circuit_external_recovery_seconds,
)

_ANALYST_ENTITY_ID = _re.compile(r"^[a-zA-Z0-9._@:/-]{1,512}$")

_graph_routing_policy: dict[str, Any] | None = None


def _load_graph_routing_policy(force: bool = False) -> dict[str, Any] | None:
    """
    OSS #42 – load graph_routing_policy_v1.json from rules path.

    The policy file is optional; if missing or invalid we treat it as disabled.
    """
    global _graph_routing_policy
    if _graph_routing_policy is not None and not force:
        return _graph_routing_policy
    path = os.path.join(settings.rules_path, "graph_routing_policy_v1.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            import json as _json_mod

            data = _json_mod.load(f)
            if not isinstance(data, dict):
                log.warning("graph routing policy not a JSON object: %s", path)
                _graph_routing_policy = None
            else:
                _graph_routing_policy = data
    except FileNotFoundError:
        log.info("graph routing policy file missing (graph_routing_policy_v1.json)")
        _graph_routing_policy = None
    except Exception as exc:
        log.warning("failed to load graph routing policy: %s", exc)
        _graph_routing_policy = None
    return _graph_routing_policy


def _graph_routing_match_when(when: list[dict[str, Any]] | None, ctx: dict[str, Any]) -> bool:
    if not when:
        return True
    for cond in when:
        if not isinstance(cond, dict):
            continue
        op = str(cond.get("op") or "").lower()
        field = cond.get("field")
        if not field:
            continue
        lhs = ctx.get(field)
        rhs = cond.get("value")
        # Normalise numeric comparisons when possible.
        if isinstance(lhs, (int, float)) or isinstance(rhs, (int, float)):
            try:
                lhs_v = float(lhs) if lhs is not None else 0.0
                rhs_v = float(rhs) if rhs is not None else 0.0
            except (TypeError, ValueError):
                return False
            if op == "lt" and not (lhs_v < rhs_v):
                return False
            if op == "lte" and not (lhs_v <= rhs_v):
                return False
            if op == "gt" and not (lhs_v > rhs_v):
                return False
            if op == "gte" and not (lhs_v >= rhs_v):
                return False
            if op == "eq" and not (lhs_v == rhs_v):
                return False
            continue
        # Fallback to string equality.
        lhs_s = "" if lhs is None else str(lhs)
        rhs_s = "" if rhs is None else str(rhs)
        if op in ("eq", "", None):
            if lhs_s != rhs_s:
                return False
    return True


def decide_graph_routing(
    event_type: str,
    base_score: float,
    tags: list[str] | None = None,
) -> dict[str, Any] | None:
    """
    OSS #42 – compute graph routing decision from policy.

    Returns a dict with ``skip_graph`` (bool) and optional ``graph_checkpoint`` and
    ``matched_rule_id`` fields, or ``None`` if no policy is configured.
    """
    policy = _load_graph_routing_policy()
    if not isinstance(policy, dict):
        return None
    ctx: dict[str, Any] = {
        "event_type": event_type,
        "base_score": float(base_score),
        "tags": tags or [],
    }
    default_cfg = policy.get("default") or {}
    result: dict[str, Any] = {
        "skip_graph": bool(default_cfg.get("skip_graph", False)),
        "graph_checkpoint": default_cfg.get("graph_checkpoint"),
        "matched_rule_id": None,
    }
    for rule in policy.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        when = rule.get("when")
        if _graph_routing_match_when(when, ctx):
            result["skip_graph"] = bool(rule.get("skip_graph", result["skip_graph"]))
            if "graph_checkpoint" in rule:
                gc = rule.get("graph_checkpoint")
                result["graph_checkpoint"] = gc if isinstance(gc, str) or gc is None else result["graph_checkpoint"]
            result["matched_rule_id"] = rule.get("id")
            break
    return result


def _circuit_metrics_inc(name: str) -> None:
    try:
        get_metrics().inc(name)
    except Exception:
        pass


async def _list_check_with_circuit(
    tenant_id: str,
    entity_id: str,
    degrade_tags: list[str],
    tenant_flags: dict[str, Any],
) -> ListCheckResult:
    if tenant_flag_enabled(tenant_flags, "disable_entity_lists"):
        degrade_tags.append("lists:disabled_by_tenant")
        return ListCheckResult(found=False, action="evaluate", reason="tenant_flag_disable_entity_lists")

    _ls = _get_list_store()

    async def _call():
        return await _ls.check(tenant_id, entity_id)

    try:
        return await _circuit_list.call(_call)
    except CircuitOpenError:
        _circuit_metrics_inc("tarka_circuit_open_total_list")
        degrade_tags.append("lists:unavailable")
        return ListCheckResult(found=False, action="evaluate", reason="circuit_open")


async def _fetch_graph_risk_wrapped(
    http: httpx.AsyncClient,
    tenant_id: str,
    entity_id: str,
    degrade_tags: list[str],
    tenant_flags: dict[str, Any],
    graph_checkpoint: str | None = None,
) -> dict[str, Any] | None:
    if tenant_flag_enabled(tenant_flags, "disable_graph"):
        degrade_tags.append("graph:disabled_by_tenant")
        return None
    try:
        return await _circuit_graph.call(lambda: _fetch_graph_risk(http, tenant_id, entity_id, graph_checkpoint))
    except CircuitOpenError:
        _circuit_metrics_inc("tarka_circuit_open_total_graph")
        degrade_tags.append("graph:unavailable")
        return None


async def _fetch_feature_snapshot_wrapped(
    http: httpx.AsyncClient,
    body: EvaluateRequest,
    redis_tag_list: list[str],
    degrade_tags: list[str],
    tenant_flags: dict[str, Any],
) -> dict[str, Any]:
    if tenant_flag_enabled(tenant_flags, "disable_feature_service"):
        degrade_tags.append("enrichment:disabled_by_tenant")
        return _feature_snapshot_fallback(body, redis_tag_list)
    try:
        return await _circuit_feature.call(lambda: _fetch_feature_snapshot(http, body, redis_tag_list))
    except CircuitOpenError:
        _circuit_metrics_inc("tarka_circuit_open_total_feature")
        degrade_tags.append("enrichment:unavailable")
        return _feature_snapshot_fallback(body, redis_tag_list)


async def _fetch_counter_snapshot(
    http: httpx.AsyncClient,
    body: EvaluateRequest,
    features: dict[str, Any],
) -> dict[str, Any] | None:
    if not settings.counter_service_url:
        return None
    url = settings.counter_service_url.rstrip("/") + "/v1/record-and-query"
    payload = {
        "tenant_id": body.tenant_id,
        "entity_id": body.entity_id,
        "event_id": str(uuid.uuid4()),
        "payload": features,
    }
    r = await http.post(
        url,
        json=payload,
        headers=_upstream_headers(),
        timeout=settings.eval_step_feature_snapshot_timeout_seconds,
    )
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, dict) else None


async def _fetch_counter_snapshot_wrapped(
    http: httpx.AsyncClient,
    body: EvaluateRequest,
    features: dict[str, Any],
    degrade_tags: list[str],
) -> dict[str, Any] | None:
    if not settings.counter_service_url:
        return None
    try:
        return await _circuit_counter.call(lambda: _fetch_counter_snapshot(http, body, features))
    except CircuitOpenError:
        _circuit_metrics_inc("tarka_circuit_open_total_counter")
        degrade_tags.append("counter:unavailable")
        return None


async def _fetch_location_evaluation(
    http: httpx.AsyncClient,
    body: EvaluateRequest,
    features: dict[str, Any],
) -> dict[str, Any] | None:
    if not settings.location_service_url:
        return None
    url = settings.location_service_url.rstrip("/") + "/v1/evaluate"
    current = None
    previous = None
    try:
        la = float(features.get("session_last_lat")) if features.get("session_last_lat") is not None else None
        lo = float(features.get("session_last_lon")) if features.get("session_last_lon") is not None else None
        lts = float(features.get("session_last_ts")) if features.get("session_last_ts") is not None else None
        if la is not None and lo is not None:
            current = {"lat": la, "lon": lo, "ts": lts, "source": str(features.get("geo_source_resolved") or "derived")}
    except (TypeError, ValueError):
        current = None
    try:
        pla = float(features.get("session_prev_lat")) if features.get("session_prev_lat") is not None else None
        plo = float(features.get("session_prev_lon")) if features.get("session_prev_lon") is not None else None
        pts = float(features.get("session_prev_ts")) if features.get("session_prev_ts") is not None else None
        if pla is not None and plo is not None:
            previous = {"lat": pla, "lon": plo, "ts": pts, "source": "previous"}
    except (TypeError, ValueError):
        previous = None
    payload = {
        "tenant_id": body.tenant_id,
        "entity_id": body.entity_id,
        "session_id": body.session_id,
        "current": current,
        "previous": previous,
        "trusted_places": load_trusted_zones_for_tenant(body.tenant_id),
        "features": features,
    }
    r = await http.post(
        url,
        json=payload,
        headers=_upstream_headers(),
        timeout=settings.eval_step_feature_snapshot_timeout_seconds,
    )
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, dict) else None


async def _fetch_location_evaluation_wrapped(
    http: httpx.AsyncClient,
    body: EvaluateRequest,
    features: dict[str, Any],
    degrade_tags: list[str],
) -> dict[str, Any] | None:
    if not settings.location_service_url:
        return None
    try:
        return await _circuit_location.call(lambda: _fetch_location_evaluation(http, body, features))
    except CircuitOpenError:
        _circuit_metrics_inc("tarka_circuit_open_total_location")
        degrade_tags.append("location:unavailable")
        return None


async def _fetch_calibration_adjustment(
    http: httpx.AsyncClient,
    body: EvaluateRequest,
    baseline_confidence: float,
    features: dict[str, Any],
) -> dict[str, Any] | None:
    if not settings.calibration_service_url:
        return None
    url = settings.calibration_service_url.rstrip("/") + "/v1/score"
    profile = str(features.get("calibration_profile") or body.payload.get("calibration_profile") or "default")
    r = await http.post(
        url,
        json={
            "tenant_id": body.tenant_id,
            "profile_id": profile,
            "baseline_confidence": baseline_confidence,
            "features": features,
        },
        headers=_upstream_headers(),
        timeout=settings.eval_step_feature_snapshot_timeout_seconds,
    )
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, dict) else None


async def _fetch_calibration_adjustment_wrapped(
    http: httpx.AsyncClient,
    body: EvaluateRequest,
    baseline_confidence: float,
    features: dict[str, Any],
    degrade_tags: list[str],
) -> dict[str, Any] | None:
    if not settings.calibration_service_url:
        return None
    try:
        return await _circuit_calibration.call(lambda: _fetch_calibration_adjustment(http, body, baseline_confidence, features))
    except CircuitOpenError:
        _circuit_metrics_inc("tarka_circuit_open_total_calibration")
        degrade_tags.append("calibration:unavailable")
        return None


async def _fetch_ml_score_wrapped(
    http: httpx.AsyncClient,
    tenant_id: str,
    entity_id: str,
    event_type: str,
    features: dict[str, Any],
    degrade_tags: list[str],
    tenant_flags: dict[str, Any],
) -> tuple[float | None, dict[str, Any]]:
    if tenant_flag_enabled(tenant_flags, "disable_ml"):
        degrade_tags.append("ml:disabled_by_tenant")
        return None, {}
    try:
        return await _circuit_ml.call(lambda: _fetch_ml_score(http, tenant_id, entity_id, event_type, features))
    except CircuitOpenError:
        _circuit_metrics_inc("tarka_circuit_open_total_ml")
        degrade_tags.append("ml:unavailable")
        return None, {}


async def _evaluate_opa_wrapped(
    http: httpx.AsyncClient,
    snapshot: dict[str, Any],
    degrade_tags: list[str],
    tenant_flags: dict[str, Any],
) -> dict[str, Any] | None:
    if tenant_flag_enabled(tenant_flags, "disable_opa"):
        degrade_tags.append("opa:disabled_by_tenant")
        return None
    try:
        return await _circuit_opa.call(
            lambda: evaluate_opa_or_raise(
                http,
                settings.opa_url,
                {"snapshot": snapshot},
                timeout_seconds=settings.eval_step_opa_timeout_seconds,
            )
        )
    except CircuitOpenError:
        _circuit_metrics_inc("tarka_circuit_open_total_opa")
        degrade_tags.append("opa:unavailable")
        return None


async def _fetch_external_signals_wrapped(
    http: httpx.AsyncClient,
    body: EvaluateRequest,
    features: dict[str, Any],
    degrade_tags: list[str],
) -> dict[str, Any] | None:
    try:
        return await _circuit_external.call(lambda: evaluate_external_signals(http, body, features))
    except CircuitOpenError:
        _circuit_metrics_inc("tarka_circuit_open_total_external")
        degrade_tags.append("external:unavailable")
        return None


def _compute_fallback_reason(degrade_tags: list[str], step_trace: list[dict[str, Any]]) -> str | None:
    """R2.4 — compact audit field when rules-only or degraded path was used."""
    tag_map = {
        "lists:unavailable": "circuit_list",
        "graph:unavailable": "circuit_graph",
        "enrichment:unavailable": "circuit_feature",
        "ml:unavailable": "circuit_ml",
        "opa:unavailable": "circuit_opa",
        "calibration:unavailable": "circuit_calibration",
        "counter:unavailable": "circuit_counter",
        "location:unavailable": "circuit_location",
        "external:unavailable": "circuit_external",
        "counter:fallback_local_agg": "counter_local_aggregate_fallback",
        "lists:disabled_by_tenant": "tenant_disable_entity_lists",
        "graph:disabled_by_tenant": "tenant_disable_graph",
        "enrichment:disabled_by_tenant": "tenant_disable_feature_service",
        "ml:disabled_by_tenant": "tenant_disable_ml",
        "opa:disabled_by_tenant": "tenant_disable_opa",
    }
    parts: list[str] = []
    seen: set[str] = set()
    for t in degrade_tags:
        code = tag_map.get(t)
        if code and code not in seen:
            seen.add(code)
            parts.append(code)
    for tr in step_trace:
        if tr.get("status") == "skipped" and tr.get("reason"):
            key = f"step_{tr.get('step', '?')}:{tr['reason']}"
            if key not in seen:
                seen.add(key)
                parts.append(key)
    if settings.score_blend_strategy == "rules_only" and "rules_only_blend" not in seen:
        parts.append("rules_only_blend")
        seen.add("rules_only_blend")
    return "; ".join(parts) if parts else None


def _normalize_explainability_tier(raw: str | None) -> str:
    tier = str(raw or "").strip().lower()
    if tier in {"minimal", "analyst", "full"}:
        return tier
    return "minimal"


def _shape_inference_context_for_tier(inference_context: dict[str, Any], tier: str) -> dict[str, Any]:
    normalized_tier = _normalize_explainability_tier(tier)
    if normalized_tier in {"analyst", "full"}:
        return _json.loads(_json.dumps(inference_context, default=str))

    out = _json.loads(_json.dumps(inference_context, default=str))
    out["graph_risk_reasons"] = []
    out["ml_top_factors"] = []
    out["ml_summary"] = None
    out["policy_experiment_id"] = None

    top_signals = out.get("top_signals")
    if isinstance(top_signals, list):
        out["top_signals"] = list(dict.fromkeys(str(s).split(":", 1)[0] for s in top_signals if str(s).strip()))

    driver_explain = out.get("driver_explain")
    if isinstance(driver_explain, list):
        compact: list[dict[str, str]] = []
        for row in driver_explain:
            if not isinstance(row, dict):
                continue
            reason = str(row.get("reason") or "").strip()
            if not reason:
                continue
            compact.append(
                {
                    "reason": reason,
                    "category": str(row.get("category") or "other"),
                    "label": "",
                }
            )
        out["driver_explain"] = compact
    return out


def _resolve_response_explainability_tier(request: Request) -> str:
    requested_raw = request.headers.get("x-tarka-explainability-tier")
    default_tier = _normalize_explainability_tier(settings.explainability_tier_default)
    user = getattr(request.state, "auth_user", None)
    can_view_analyst = bool(user and hasattr(user, "has_role") and user.has_role("analyst"))

    if requested_raw is not None:
        requested = _normalize_explainability_tier(requested_raw)
        if requested in {"analyst", "full"} and not can_view_analyst:
            return "minimal"
        return requested

    if default_tier in {"analyst", "full"} and not can_view_analyst:
        return "minimal"
    return default_tier


def _audit_counter_version_label() -> str:
    """Align with AggregateStore / replay keying (``AGG_KEY_VERSION``); stable default when unset."""
    v = (os.environ.get("AGG_KEY_VERSION") or "").strip()
    return v if v else "default"


def _build_artifact_manifest(
    *,
    json_rule_pack_files: list[str],
    inf_ctx: dict[str, Any],
    graph_checkpoint: str | None,
    external_signal_meta: dict[str, Any] | None,
    challenge_policy_id: str | None,
) -> dict[str, Any]:
    rule_pack_joined = ",".join(sorted(str(x).strip() for x in json_rule_pack_files if str(x).strip()))
    return {
        "decision_api_revision": (os.environ.get("GIT_SHA") or os.environ.get("COMMIT_SHA") or "").strip(),
        "inference_schema_version": INFERENCE_SCHEMA_VERSION,
        "rule_pack_files": sorted(str(x).strip() for x in json_rule_pack_files if str(x).strip()),
        "rule_pack_fingerprint_sha256": hashlib.sha256(rule_pack_joined.encode("utf-8")).hexdigest() if rule_pack_joined else "",
        "score_blend_strategy": settings.score_blend_strategy,
        "counter_version": _audit_counter_version_label(),
        "ml_model": str(inf_ctx.get("ml_model") or ""),
        "graph_checkpoint": graph_checkpoint or "",
        "policy_experiment_id": str(inf_ctx.get("policy_experiment_id") or ""),
        "challenge_policy_id": challenge_policy_id or "",
        "consortium_hash_scope": settings.consortium_hash_scope,
        "external_signal_providers": list((external_signal_meta or {}).get("providers") or []),
    }


def _metadata_etl_batch_id(body: EvaluateRequest) -> str | None:
    """Epic X.2 — optional lineage id from evaluate ``metadata`` (e.g. propagated from ingest v1 envelope)."""
    md = body.metadata
    if not isinstance(md, dict):
        return None
    v = md.get("etl_batch_id")
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    return s[:256]


def _velocity_anomaly_flags(features: dict[str, Any]) -> dict[str, Any]:
    """Heuristic flags for analyst / copilot tooling only (not a decision)."""
    ev5 = int(features.get("event_count_5m") or 0)
    ev1 = int(features.get("event_count_1h") or 0)
    ev24 = int(features.get("event_count_24h") or 0)
    flags: list[str] = []
    if ev5 >= 5:
        flags.append("burst_activity_5m")
    if ev1 >= 15:
        flags.append("high_volume_1h")
    if ev24 > 0 and ev1 > 10 and (ev1 / max(ev24, 1)) > 0.4:
        flags.append("concentrated_recent_activity_vs_24h")
    dd = int(features.get("distinct_device_id_24h") or 0)
    if dd >= 3:
        flags.append("multiple_distinct_devices_24h")
    sev = "low"
    if len(flags) >= 2:
        sev = "high"
    elif flags:
        sev = "medium"
    return {"flags": flags, "severity_hint": sev}


# ---------- websocket live feed ----------
_ws_clients: dict[WebSocket, str] = {}

# Last time rules/typology/predicate materialization completed (for ops UX; OSS #36).
_RULES_MATERIALIZED_AT: float | None = None


def _touch_rules_materialized() -> None:
    global _RULES_MATERIALIZED_AT
    _RULES_MATERIALIZED_AT = time.time()


async def _broadcast_decision(data: dict) -> None:
    if not _ws_clients:
        return
    msg = _json.dumps(data, default=str)
    tenant_id = str(data.get("tenant_id") or "").strip()
    dead: list[WebSocket] = []
    for ws, subscribed_tenant in _ws_clients.items():
        if tenant_id and subscribed_tenant not in {tenant_id, "*"}:
            continue
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.pop(ws, None)


# ---------- auth ----------

_valid_api_keys: frozenset[str] | None = None


def _get_api_keys() -> frozenset[str]:
    global _valid_api_keys
    if _valid_api_keys is None:
        raw = settings.api_keys.strip()
        _valid_api_keys = frozenset(k.strip() for k in raw.split(",") if k.strip()) if raw else frozenset()
    return _valid_api_keys


async def require_api_key(request: Request) -> None:
    keys = _get_api_keys()
    if not keys:
        allow = os.environ.get("ALLOW_INSECURE_NO_AUTH", "").strip().lower() in {"1", "true", "yes", "on"}
        if allow:
            return
        raise HTTPException(
            status_code=503,
            detail="service auth misconfigured: API_KEYS is empty (set API_KEYS or ALLOW_INSECURE_NO_AUTH=true for local development)",
        )
    header = request.headers.get("x-api-key", "")
    if header not in keys:
        raise HTTPException(status_code=401, detail="invalid or missing API key")


# ---------- lifespan ----------


@asynccontextmanager
async def lifespan(application: FastAPI):
    await init_db()
    await redis_tags.connect()
    load_rules()
    load_typology_definitions()
    _touch_rules_materialized()
    load_challenge_policies(force=True)
    load_shadow_rules()
    if redis_tags._client:
        agg_store.set_client(redis_tags._client)
        fingerprint_store.set_client(redis_tags._client)
        entity_link_store.set_client(redis_tags._client)
    _list_store = create_list_store(
        backend=settings.list_store_backend,
        redis_url=settings.redis_url,
        file_dir=settings.list_store_file_dir,
        api_url=settings.list_store_api_url,
        api_key=settings.list_store_api_key,
    )
    await _list_store.connect()
    set_store(_list_store)
    application.state.list_store = _list_store

    application.state.http = httpx.AsyncClient(
        timeout=httpx.Timeout(5.0, connect=2.0),
        limits=httpx.Limits(max_connections=200, max_keepalive_connections=40),
    )

    application.state.eval_load_guard = EvalLoadGuard(settings.tarka_max_concurrent_evaluations)

    application.state.nats_nc = None
    application.state.nats_js = None
    if settings.nats_url:
        try:
            nc = await nats.connect(settings.nats_url)
            application.state.nats_nc = nc
            application.state.nats_js = nc.jetstream()
            log.info("Connected to NATS at %s", settings.nats_url)
        except Exception as e:
            log.warning("NATS connection failed (publishing disabled): %s", e)

    retention_task = None
    if DEFAULT_RETENTION_DAYS > 0:
        retention_task = asyncio.create_task(retention_loop())

    yield

    if hasattr(application.state, "list_store") and application.state.list_store:
        await application.state.list_store.close()
    if retention_task:
        retention_task.cancel()
    if application.state.nats_nc:
        await application.state.nats_nc.drain()
    await application.state.http.aclose()
    await redis_tags.close()


app = FastAPI(
    title="Tarka Decision API",
    version="4.0.0",
    lifespan=lifespan,
)
if os.environ.get("TARKA_CORE_API_SUBAPP", "").strip() != "1":
    setup_observability(app, "decision-api")
setup_security_headers(app)
setup_auth(app)
setup_rate_limiter(app, rpm=int(os.environ.get("RATE_LIMIT_RPM", "1000")))

if settings.request_signature_secret:
    from decision_api.request_signature_middleware import RequestSignatureMiddleware

    app.add_middleware(
        RequestSignatureMiddleware,
        secret=settings.request_signature_secret,
        max_skew_seconds=settings.request_signature_max_skew_seconds,
    )

from decision_api.analytics_dashboards import router as analytics_dashboards_router  # noqa: E402
from decision_api.backtest_api import router as backtest_router  # noqa: E402
from decision_api.calibration_api import router as calibration_router  # noqa: E402
from decision_api.captcha import router as captcha_router  # noqa: E402
from decision_api.compliance_api import router as compliance_router  # noqa: E402
from decision_api.consortium_api import router as consortium_router  # noqa: E402
from decision_api.feature_store_api import router as feature_store_router  # noqa: E402
from decision_api.experiment_api import experiment_registry_line_count  # noqa: E402
from decision_api.experiment_api import router as experiment_router  # noqa: E402
from decision_api.internal_counters_api import router as internal_counters_router  # noqa: E402
from decision_api.recommend_api import router as recommend_router  # noqa: E402
from decision_api.replay import router as replay_router  # noqa: E402
from decision_api.reporting_nl import router as reporting_nl_router  # noqa: E402
from decision_api.rule_api import router as rule_router  # noqa: E402
from decision_api.rule_compiler_api import router as rule_compiler_router  # noqa: E402
from decision_api.rule_gitops_api import router as rule_gitops_router  # noqa: E402
from decision_api.simulation_api import router as simulation_router  # noqa: E402
from decision_api.vendor_marketplace_api import router as vendor_marketplace_router  # noqa: E402

app.include_router(rule_router)
app.include_router(replay_router)
app.include_router(simulation_router)
app.include_router(experiment_router)
app.include_router(recommend_router)
app.include_router(compliance_router)
app.include_router(captcha_router)
app.include_router(lists_router)
app.include_router(consortium_router)
app.include_router(internal_counters_router)
app.include_router(calibration_router)
app.include_router(reporting_nl_router)
app.include_router(rule_compiler_router)
app.include_router(rule_gitops_router)
app.include_router(backtest_router)
app.include_router(feature_store_router)
app.include_router(analytics_dashboards_router)
app.include_router(vendor_marketplace_router)


def _http(request: Request) -> httpx.AsyncClient:
    return request.app.state.http


# ---------- health ----------


@app.get("/v1/health")
async def health():
    return {"status": "ok"}


@app.get("/v1/slo")
async def slo_status():
    """In-process SLO snapshot (v1.2.5 R1) — targets are aspirational; ``current`` from local HTTP metrics."""
    m = get_metrics()
    cur = m.request_count_summary()
    return {
        "service": "decision-api",
        "availability_target_pct": 99.9,
        "latency_target_ms_p95": 50,
        "error_budget_window_days": 30,
        "targets_note": "Latency/availability measured vs your SLO stack (Prometheus/Grafana); this endpoint exposes in-process counters only.",
        "current": {
            **cur,
            "redis_connected": redis_tags._client is not None,
            "nats_connected": getattr(app.state, "nats_nc", None) is not None,
            "evaluate_require_idempotency_key": settings.evaluate_require_idempotency_key,
        },
    }


@app.get("/v1/ops/evaluation-posture")
async def evaluation_posture(request: Request):
    """Analyst/ops surface: deployment tier hint, evaluation mode, and compliance readiness (OSS #36)."""
    mode = (settings.tarka_evaluation_mode or "detection").strip().lower()
    if mode not in ("detection", "compliance"):
        mode = "detection"

    explicit_tier = (settings.tarka_deployment_tier or "").strip().lower()
    if explicit_tier in ("community", "pro"):
        deployment_tier = explicit_tier
    else:
        has_graph = bool((settings.graph_service_url or "").strip())
        has_nats = bool((settings.nats_url or "").strip())
        has_ml_plane = bool((settings.feature_service_url or "").strip() or (settings.ml_scoring_url or "").strip())
        if not has_graph and not has_nats and not has_ml_plane:
            deployment_tier = "community"
        else:
            deployment_tier = "pro"

    data = load_typology_definitions()
    typologies = data.get("typologies") if isinstance(data.get("typologies"), list) else []
    typology_count = len([t for t in typologies if isinstance(t, dict) and str(t.get("id") or "").strip()])

    registry = load_predicate_registry()
    reg_ver = int(registry.get("version") or 0)
    pin = data.get("predicate_registry_pin")
    try:
        pin_int = int(pin) if pin is not None else reg_ver
    except (TypeError, ValueError):
        pin_int = reg_ver
    pin_match = reg_ver == pin_int

    degraded_reasons: list[str] = []
    if typology_count == 0:
        degraded_reasons.append("typologies_empty")
    if not pin_match:
        degraded_reasons.append("predicate_registry_pin_mismatch")

    compliance_degraded = mode == "compliance" and bool(degraded_reasons)
    posture = "degraded" if compliance_degraded else "ready"

    deps: list[dict[str, Any]] = [
        {
            "id": "redis",
            "ok": redis_tags._client is not None,
            "detail": "connected" if redis_tags._client else "not_connected",
        },
        {
            "id": "graph_service_configured",
            "ok": bool((settings.graph_service_url or "").strip()),
            "detail": "set" if (settings.graph_service_url or "").strip() else "empty",
        },
        {
            "id": "feature_service_configured",
            "ok": bool((settings.feature_service_url or "").strip()),
            "detail": "set" if (settings.feature_service_url or "").strip() else "empty",
        },
        {
            "id": "ml_scoring_configured",
            "ok": bool((settings.ml_scoring_url or "").strip()),
            "detail": "set" if (settings.ml_scoring_url or "").strip() else "empty",
        },
        {
            "id": "nats_configured",
            "ok": bool((settings.nats_url or "").strip()),
            "detail": "set" if (settings.nats_url or "").strip() else "empty",
        },
        {
            "id": "opa_configured",
            "ok": bool((settings.opa_url or "").strip()),
            "detail": "set" if (settings.opa_url or "").strip() else "empty",
        },
    ]

    last_reload = _RULES_MATERIALIZED_AT
    last_reload_iso: str | None
    if last_reload is None:
        last_reload_iso = None
    else:
        last_reload_iso = datetime.fromtimestamp(last_reload, tz=timezone.utc).isoformat().replace("+00:00", "Z")

    runbook = "https://github.com/pamu512/tarka/blob/master/docs/docs/guides/deployment-profiles-community-vs-pro.md"

    trp = (settings.tarka_tenant_reliability_profile or "balanced").strip().lower()
    if trp not in ("strict", "balanced", "permissive"):
        trp = "balanced"

    return {
        "service": "decision-api",
        "deployment_tier": deployment_tier,
        "evaluation_mode": mode,
        "tenant_reliability_profile": trp,
        "compliance_posture": posture,
        "compliance_degraded": compliance_degraded,
        "compliance_degraded_reasons": degraded_reasons if mode == "compliance" else [],
        "typology_count": typology_count,
        "predicate_registry_version": reg_ver,
        "predicate_registry_pin_match": pin_match,
        "dependencies": deps,
        "dependency_resilience_policy": dependency_resilience_policy_table(),
        "last_rules_reload_at": last_reload_iso,
        "runbook_url": runbook,
        "request_id": request.headers.get("x-request-id") or request.headers.get("x-correlation-id"),
    }


# ---------- attestation ----------


class ChallengeRequest(BaseModel):
    tenant_id: str


class VerifyRequest(BaseModel):
    nonce: str
    token: str
    provider: str


@app.post("/v1/attestation/challenge")
async def attestation_challenge(body: ChallengeRequest):
    nonce = os.urandom(32).hex()
    ttl = settings.attestation_nonce_ttl
    await redis_tags.store_nonce(nonce, ttl)
    return {"nonce": nonce, "expires_in": ttl}


@app.post("/v1/attestation/verify")
async def attestation_verify(body: VerifyRequest):
    consumed = await redis_tags.consume_nonce(body.nonce)
    if not consumed:
        raise HTTPException(400, "invalid or expired nonce")

    if body.provider == "browser_challenge":
        if not settings.attestation_hmac_secret:
            return {"valid": True, "device_integrity": "unverified_no_secret"}
        expected = hmac.new(
            settings.attestation_hmac_secret.encode(),
            body.nonce.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, body.token):
            return {"valid": False, "device_integrity": None, "reason": "hmac_mismatch"}
        return {"valid": True, "device_integrity": "browser_verified"}

    if body.provider == "play_integrity":
        # Google Play Integrity: the token is a signed JWS that must be verified
        # via Google's playintegrity.googleapis.com/v1/{package}:decodeIntegrityToken
        # This requires GOOGLE_CLOUD_PROJECT and a service account.
        if not body.token or len(body.token) < 50:
            return {"valid": False, "device_integrity": None, "reason": "invalid_token_format"}
        log.warning("Play Integrity token received but server-side verification not configured. Set PLAY_INTEGRITY_CREDENTIALS to enable full verification.")
        return {"valid": True, "device_integrity": "play_integrity_unverified", "warning": "Server-side verification pending configuration"}

    if body.provider == "app_attest":
        # Apple App Attest: token is a CBOR-encoded attestation object.
        # Requires server-side verification with Apple's attestation service.
        if not body.token or len(body.token) < 50:
            return {"valid": False, "device_integrity": None, "reason": "invalid_token_format"}
        log.warning("App Attest token received but server-side verification not configured. Set APP_ATTEST_TEAM_ID to enable full verification.")
        return {"valid": True, "device_integrity": "app_attest_unverified", "warning": "Server-side verification pending configuration"}

    return {"valid": False, "device_integrity": None, "reason": "unknown_provider"}


# ---------- admin ----------


@app.post("/v1/admin/rules/reload")
async def reload_rules(_=Depends(require_role("admin"))):
    load_rules()
    reload_typology_definitions()
    reload_predicate_registry()
    _touch_rules_materialized()
    _load_graph_routing_policy(force=True)
    load_challenge_policies(force=True)
    _load_graph_routing_policy(force=True)
    return {"ok": True}


@app.get("/v1/admin/typology/predicate-registry")
async def get_typology_predicate_registry(_=Depends(require_role("admin"))):
    """OSS #46 — named predicate catalog (version pin must match typology_definitions ``predicate_registry_pin``)."""
    return {"ok": True, **registry_public_view()}


@app.get("/v1/ops/governance")
async def ops_governance():
    """Rollout posture: active rule packs (canary, effective_at), shadow count, inference contract version."""
    exp_ct = experiment_registry_line_count()
    g = rules_governance_summary()
    cal_status: dict[str, Any]
    if settings.calibration_service_url:
        try:
            r = await app.state.http.get(
                settings.calibration_service_url.rstrip("/") + "/v1/drift",
                params={"tenant_id": "global", "profile_id": "default"},
                timeout=settings.eval_step_feature_snapshot_timeout_seconds,
            )
            r.raise_for_status()
            data = r.json()
            cal_status = data if isinstance(data, dict) else {"hint": "invalid_calibration_response"}
        except Exception:
            cal_status = {"hint": "calibration_service_unavailable"}
    else:
        cal_status = {"hint": "calibration_service_not_configured"}
    return {
        "inference_schema_version": INFERENCE_SCHEMA_VERSION,
        "rule_packs": g,
        "counter_catalog": {
            "endpoint": "GET /v1/internal/counters/catalog",
            "manifest": "GET /v1/internal/counters/manifest",
            "file": "decision_api/data/counter_catalog.json (merged with counter_manifest_v1.json)",
        },
        "experiment_registry_lines": exp_ct,
        "calibration_status": cal_status,
        "drift_smoke": {
            "script": "scripts/benchmarks/drift_score_smoke.py",
            "note": "Run baseline vs shifted batches to guard scorer separation; not full calibration.",
        },
        "calibration_api": {
            "prefix": "/v1/calibration",
            "note": "POST snapshots, pin reference, GET drift — file-backed under rules/calibration_data/ or CALIBRATION_DATA_DIR",
        },
        "nats_prometheus": {
            "script": "scripts/observability/nats_jetstream_exporter.py",
            "note": "Poll JetStream; pipe stdout to node_exporter textfile collector or cron + curl pushgateway",
        },
        "contract_fuzz": {
            "script": "scripts/contract/fuzz_decision_api.py",
            "note": "Health + OpenAPI reachability; use schemathesis CLI for property-based fuzz",
        },
        "mobile_attestation_taxonomy": {
            "doc": "docs/docs/guides/mobile-attestation-taxonomy.md",
            "attestation_schema_version": 1,
            "note": "Normalized on EvaluateRequest.device_context.attestation (Play Integrity + App Attest).",
        },
        "tenant_flags": {
            "redis_key": "fraud:tenant_flags:{tenant_id}",
            "get": "GET /v1/admin/tenants/{tenant_id}/flags",
            "patch": "PATCH /v1/admin/tenants/{tenant_id}/flags",
            "keys": [
                "disable_graph",
                "disable_feature_service",
                "disable_ml",
                "disable_opa",
                "disable_entity_lists",
            ],
            "evaluate_response": "fallback_reason when degraded (R2.4)",
        },
    }


@app.get("/v1/ops/calibration-status")
async def calibration_status(tenant_id: str, profile: str = "default"):
    """Small ops view that combines drift hint with governance context."""
    if settings.calibration_service_url:
        try:
            r = await app.state.http.get(
                settings.calibration_service_url.rstrip("/") + "/v1/drift",
                params={"tenant_id": tenant_id, "profile_id": profile},
                timeout=settings.eval_step_feature_snapshot_timeout_seconds,
            )
            r.raise_for_status()
            data = r.json()
            drift = data if isinstance(data, dict) else {"hint": "invalid_calibration_response"}
        except Exception:
            drift = {"hint": "calibration_service_unavailable"}
    else:
        drift = {"hint": "calibration_service_not_configured"}
    return {
        "tenant_id": tenant_id,
        "profile": profile,
        "inference_schema_version": INFERENCE_SCHEMA_VERSION,
        "challenge_policy_default": settings.challenge_policy_default,
        "calibration": drift,
    }


@app.get("/v1/challenge-policies")
async def list_challenge_policy_templates():
    """List loaded challenge / escalation policy templates (JSON under rules/challenge_policies/)."""
    from decision_api.challenge_policy import get_policy_summaries

    return {"policies": get_policy_summaries()}


@app.post("/v1/admin/shadow/reload")
async def reload_shadow(_=Depends(require_role("admin"))):
    load_shadow_rules()
    return {"ok": True}


class TenantFlagsBody(BaseModel):
    """Kill-switch flags stored in Redis JSON ``fraud:tenant_flags:{tenant_id}`` (R2.3)."""

    disable_graph: bool | None = None
    disable_feature_service: bool | None = None
    disable_ml: bool | None = None
    disable_opa: bool | None = None
    disable_entity_lists: bool | None = None


@app.get("/v1/admin/tenants/{tenant_id}/flags")
async def get_tenant_flags_admin(tenant_id: str, _=Depends(require_role("admin"))):
    if not redis_tags._client:
        raise HTTPException(503, detail="Redis not configured")
    flags = await redis_tags.get_tenant_flags(tenant_id)
    return {"tenant_id": tenant_id, "flags": flags}


@app.patch("/v1/admin/tenants/{tenant_id}/flags")
async def patch_tenant_flags_admin(tenant_id: str, body: TenantFlagsBody, _=Depends(require_role("admin"))):
    if not redis_tags._client:
        raise HTTPException(503, detail="Redis not configured")
    updates = body.model_dump(exclude_none=True)
    merged = await redis_tags.patch_tenant_flags(tenant_id, updates)
    return {"tenant_id": tenant_id, "flags": merged}


# ---------- signal tag extraction ----------

_SIGNAL_TAG_MAP = {
    "is_emulator": "sdk:emulator",
    "is_vpn": "sdk:vpn",
    "is_bot": "sdk:bot",
    "is_repackaged": "sdk:repackaged",
    "is_spoofed_location": "sdk:spoofed_location",
    "webdriver_detected": "sdk:webdriver",
    "headless_detected": "sdk:headless",
    "automation_detected": "sdk:automation",
    "timezone_geo_mismatch": "sdk:tz_geo_mismatch",
    "vpn_interface_detected": "sdk:vpn_iface",
    "mock_location_detected": "sdk:mock_location",
    "geo_ip_mismatch": "sdk:geo_ip_mismatch",
    "geo_tz_mismatch": "sdk:geo_tz_mismatch",
    "ip_is_proxy": "sdk:proxy",
    "ip_is_datacenter": "sdk:datacenter",
}


def extract_signal_tags(device_context: dict[str, Any] | None) -> list[str]:
    if not device_context:
        return []
    signals = device_context.get("signals") or {}
    tags: list[str] = []
    for key, tag in _SIGNAL_TAG_MAP.items():
        if signals.get(key) is True:
            tags.append(tag)
    if signals.get("attestation_verified") is True:
        tags.append("sdk:attestation_verified")
    att = device_context.get("attestation")
    if isinstance(att, dict) and att.get("verified") is True:
        tags.append("sdk:attestation_verified")
    tags.extend(attestation_signal_tags(device_context))
    return list(dict.fromkeys(tags))


def extract_captcha_tags(dc: dict | None) -> list[str]:
    """Extract CAPTCHA verification results as tags."""
    tags = []
    if not dc:
        return tags
    signals = dc.get("signals", {})
    captcha = signals.get("captcha")
    if not captcha:
        tags.append("captcha:none")
        return tags

    provider = captcha.get("provider", "unknown")
    success = captcha.get("success", False)
    score = captcha.get("score")

    if success:
        tags.append(f"captcha:{provider}:pass")
    else:
        tags.append(f"captcha:{provider}:fail")

    if score is not None:
        if score < 0.3:
            tags.append("captcha:score_low")
        elif score < 0.7:
            tags.append("captcha:score_medium")
        else:
            tags.append("captcha:score_high")

    if captcha.get("error_codes"):
        tags.append("captcha:has_errors")

    return tags


def _infer_ctx_kwargs(body: EvaluateRequest, features: dict[str, Any]) -> dict[str, Any]:
    """Platform + optional TLS pinning hint for inference / integrity policy."""
    plat = "web"
    if body.device_context:
        plat = str(body.device_context.platform or "web").strip().lower() or "web"
    pin: bool | None = None
    if isinstance(body.metadata, dict):
        raw = body.metadata.get("tls_pinning_verified")
        if isinstance(raw, bool):
            pin = raw
        elif isinstance(raw, str):
            pin = raw.strip().lower() in ("1", "true", "yes")
    if isinstance(body.payload, dict):
        tz = body.payload.get("trusted_zones")
        if isinstance(tz, list):
            features.setdefault("trusted_zones", tz)
        disk_zones = load_trusted_zones_for_tenant(body.tenant_id)
        if disk_zones:
            merged: list = []
            if isinstance(features.get("trusted_zones"), list):
                merged = [x for x in features["trusted_zones"] if isinstance(x, dict)]
            seen = {_json.dumps(x, sort_keys=True) for x in merged}
            for z in disk_zones:
                key = _json.dumps(z, sort_keys=True)
                if key not in seen:
                    merged.append(z)
                    seen.add(key)
            features["trusted_zones"] = merged
        for key in (
            "session_last_lat",
            "session_last_lon",
            "session_last_ts",
            "session_prev_lat",
            "session_prev_lon",
            "session_prev_ts",
            "calibration_bias",
            "calibration_profile",
            "expected_calibration_version",
        ):
            if key in body.payload and body.payload[key] is not None:
                features.setdefault(key, body.payload[key])
    return {"platform": plat, "tls_pinning_verified": pin}


def extract_behavior_tags(device_context: dict[str, Any] | None) -> list[str]:
    if not device_context:
        return []
    behavior = device_context.get("behavior") or {}
    bot = behavior.get("bot_indicators") or {}
    tags: list[str] = []
    if bot.get("zero_mouse_movement"):
        tags.append("behavior:no_mouse")
    if bot.get("constant_typing_speed"):
        tags.append("behavior:constant_typing")
    if bot.get("no_scroll"):
        tags.append("behavior:no_scroll")
    if bot.get("suspiciously_fast"):
        tags.append("behavior:fast_typing")
    session = behavior.get("session") or {}
    if session.get("paste_count", 0) > 3:
        tags.append("behavior:heavy_paste")
    if session.get("tab_switches", 0) > 10:
        tags.append("behavior:excessive_tab_switch")
    typing = behavior.get("typing") or {}
    if typing.get("avg_inter_key_ms", 999) < 25 and typing.get("key_count", 0) > 30:
        tags.append("behavior:superhuman_typing")
    return tags


# ---------- downstream helpers ----------


def _feature_snapshot_fallback(body: EvaluateRequest, redis_tag_list: list[str]) -> dict[str, Any]:
    return {
        "tenant_id": body.tenant_id,
        "entity_id": body.entity_id,
        "event_type": body.event_type.value,
        "features": dict(body.payload),
        "redis_tags": redis_tag_list,
    }


async def _fetch_feature_snapshot(http: httpx.AsyncClient, body: EvaluateRequest, redis_tag_list: list[str]) -> dict[str, Any]:
    if not settings.feature_service_url:
        return _feature_snapshot_fallback(body, redis_tag_list)
    url = settings.feature_service_url.rstrip("/") + "/v1/snapshot"
    r = await http.post(
        url,
        json={
            "tenant_id": body.tenant_id,
            "entity_id": body.entity_id,
            "event_type": body.event_type.value,
            "payload": body.payload,
        },
        headers=_upstream_headers(),
        timeout=settings.eval_step_feature_snapshot_timeout_seconds,
    )
    r.raise_for_status()
    return r.json()


async def _fetch_ml_score(
    http: httpx.AsyncClient, tenant_id: str, entity_id: str, event_type: str, features: dict[str, Any]
) -> tuple[float | None, dict[str, Any]]:
    """Return blended ML score plus optional explanation slice from ml-scoring (v1.2 inference_context)."""
    empty: dict[str, Any] = {}
    if not settings.ml_scoring_url:
        return None, empty
    url = settings.ml_scoring_url.rstrip("/") + "/v1/score"
    r = await http.post(
        url,
        json={
            "tenant_id": tenant_id,
            "entity_id": entity_id,
            "event_type": event_type,
            "features": features,
        },
        headers=_upstream_headers(),
        timeout=settings.eval_step_ml_timeout_seconds,
    )
    r.raise_for_status()
    data = r.json()
    score = float(data.get("score", 0))
    factors = data.get("ml_top_factors")
    if not isinstance(factors, list):
        factors = []
    summary = data.get("ml_summary")
    if summary is not None and not isinstance(summary, str):
        summary = str(summary)[:500]
    model = data.get("model")
    return score, {
        "top_factors": factors,
        "summary": summary,
        "model": model if isinstance(model, str) else None,
    }


def _quantize_place_cell(lat: float, lon: float, precision: int = 3) -> str:
    """Stable coarse place id for co-presence (no external API)."""
    return f"cell:{precision}:{round(lat, precision)}:{round(lon, precision)}"


async def _graph_upsert(
    http: httpx.AsyncClient,
    body: EvaluateRequest,
    trace_id: str,
    merged_tags: list[str],
    geo_extra_tags: list[str] | None = None,
) -> None:
    if not settings.graph_service_url:
        return
    base = settings.graph_service_url.rstrip("/")

    # Upsert Account node with tags
    await http.post(
        f"{base}/v1/entities",
        json={
            "tenant_id": body.tenant_id,
            "entity_type": "Account",
            "external_id": body.entity_id,
            "properties": {"last_event": body.event_type.value, "trace_id": trace_id},
            "tags": merged_tags,
        },
        headers=_upstream_headers(),
    )

    # Upsert Device node if device_context present
    if body.device_context:
        dc = body.device_context
        device_tags = extract_signal_tags(dc.model_dump())
        await http.post(
            f"{base}/v1/entities",
            json={
                "tenant_id": body.tenant_id,
                "entity_type": "Device",
                "external_id": dc.device_id,
                "properties": {
                    "platform": dc.platform,
                    **{k: v for k, v in dc.signals.items() if isinstance(v, (str, bool, int, float)) or v is None},
                },
                "tags": device_tags,
            },
            headers=_upstream_headers(),
        )
        # Link Account -> Device
        await http.post(
            f"{base}/v1/links",
            json={
                "tenant_id": body.tenant_id,
                "from_external_id": body.entity_id,
                "to_external_id": dc.device_id,
                "relationship": "USED",
                "properties": {"trace_id": trace_id, "event_type": body.event_type.value},
            },
            headers=_upstream_headers(),
        )

    # Upsert Session node if session_id present
    if body.session_id:
        await http.post(
            f"{base}/v1/entities",
            json={
                "tenant_id": body.tenant_id,
                "entity_type": "Custom",
                "external_id": body.session_id,
                "properties": {"type": "session", "trace_id": trace_id},
                "tags": [],
            },
            headers=_upstream_headers(),
        )
        await http.post(
            f"{base}/v1/links",
            json={
                "tenant_id": body.tenant_id,
                "from_external_id": body.entity_id,
                "to_external_id": body.session_id,
                "relationship": "USED",
                "properties": {"trace_id": trace_id},
            },
            headers=_upstream_headers(),
        )

    # Place cell for co-location (quantized lat/lon from SDK or payload hints)
    sig: dict[str, Any] = {}
    if body.device_context:
        sig = body.device_context.signals or {}
    pay = body.payload if isinstance(body.payload, dict) else {}
    la_raw = sig.get("geo_lat", pay.get("session_last_lat"))
    lo_raw = sig.get("geo_lon", pay.get("session_last_lon"))
    try:
        la_f = float(la_raw) if la_raw is not None else None
        lo_f = float(lo_raw) if lo_raw is not None else None
    except (TypeError, ValueError):
        la_f, lo_f = None, None
    if la_f is not None and lo_f is not None and -90 <= la_f <= 90 and -180 <= lo_f <= 180:
        cell = _quantize_place_cell(la_f, lo_f)
        gtags = list(geo_extra_tags or [])
        await http.post(
            f"{base}/v1/entities",
            json={
                "tenant_id": body.tenant_id,
                "entity_type": "Place",
                "external_id": cell,
                "properties": {
                    "kind": "geohash_like_cell",
                    "lat": round(la_f, 5),
                    "lon": round(lo_f, 5),
                    "trace_id": trace_id,
                },
                "tags": gtags,
            },
            headers=_upstream_headers(),
        )
        await http.post(
            f"{base}/v1/links",
            json={
                "tenant_id": body.tenant_id,
                "from_external_id": body.entity_id,
                "to_external_id": cell,
                "relationship": "SEEN_AT",
                "properties": {"trace_id": trace_id, "event_type": body.event_type.value},
            },
            headers=_upstream_headers(),
        )
        if body.session_id:
            await http.post(
                f"{base}/v1/links",
                json={
                    "tenant_id": body.tenant_id,
                    "from_external_id": body.session_id,
                    "to_external_id": cell,
                    "relationship": "SEEN_AT",
                    "properties": {"trace_id": trace_id},
                },
                headers=_upstream_headers(),
            )


async def _graph_upsert_stepped(
    http: httpx.AsyncClient,
    body: EvaluateRequest,
    trace_id: str,
    merged_tags: list[str],
    geo_extra_tags: list[str] | None,
    tenant_flags: dict[str, Any],
) -> None:
    """Background graph writes with overall timeout (#32)."""
    if tenant_flag_enabled(tenant_flags, "disable_graph"):
        return

    async def _do():
        await _graph_upsert(http, body, trace_id, merged_tags, geo_extra_tags)

    _, trace = await run_evaluation_step(
        "graph_upsert",
        _do,
        timeout_seconds=settings.eval_step_graph_upsert_timeout_seconds,
        max_attempts=settings.eval_step_graph_upsert_max_attempts,
        on_failure="SKIP",
        fallback=None,
    )
    if trace.get("status") != "ok":
        log.warning("graph_upsert step did not complete: %s", trace)


def _graph_checkpoint_from_body(body: EvaluateRequest) -> str | None:
    mk = settings.graph_checkpoint_metadata_key
    if isinstance(body.metadata, dict):
        v = body.metadata.get(mk) or body.metadata.get("graph_checkpoint")
        if isinstance(v, str) and v.strip():
            return v.strip()
    if isinstance(body.payload, dict):
        v = body.payload.get("graph_checkpoint")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


async def _fetch_graph_risk(
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
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, dict) else None


def _blend_scores(rule_score: float, ml_score: float | None) -> float:
    strategy = settings.score_blend_strategy
    if ml_score is None or strategy == "rules_only":
        return max(0.0, min(100.0, rule_score))
    if strategy == "max":
        return max(0.0, min(100.0, max(rule_score, ml_score)))
    # default: average
    return max(0.0, min(100.0, (rule_score + ml_score) / 2))


# ---------- NATS decision publishing ----------


async def _publish_decision(app_state: Any, decision_data: dict) -> None:
    js = app_state.nats_js
    if not js:
        return
    tenant = decision_data.get("tenant_id", "unknown")
    etype = decision_data.get("event_type", "unknown")
    subject = f"fraud.decisions.{tenant}.{etype}"
    try:
        await js.publish(subject, _json.dumps(decision_data, default=str).encode())
    except Exception as e:
        log.warning("Failed to publish decision to NATS: %s", e)


# ---------- shadow evaluation ----------


async def _run_shadow_evaluation(
    app_state: Any,
    features: dict[str, Any],
    redis_tag_list: list[str],
    production_decision: str,
    production_score: float,
    tenant_id: str,
    trace_id: str,
) -> None:
    shadow_result = evaluate_shadow(features, redis_tag_list)
    if shadow_result is None:
        return
    shadow_decision = shadow_result["shadow_decision"]
    if shadow_decision != production_decision:
        log.warning(
            "SHADOW DIVERGENCE: production=%s shadow=%s trace_id=%s",
            production_decision,
            shadow_decision,
            trace_id,
        )
    record_observation(
        trace_id,
        {"decision": production_decision, "score": production_score},
        shadow_result,
    )
    js = app_state.nats_js
    if js:
        subject = f"fraud.shadow.{tenant_id}"
        payload = {
            "trace_id": trace_id,
            "tenant_id": tenant_id,
            "production_decision": production_decision,
            **shadow_result,
        }
        try:
            await js.publish(subject, _json.dumps(payload, default=str).encode())
        except Exception as e:
            log.warning("Failed to publish shadow result to NATS: %s", e)


# ---------- main endpoint ----------


@app.post("/v1/decisions/evaluate", response_model=EvaluateResponse)
async def evaluate_decision(
    body: EvaluateRequest,
    request: Request,
    bg: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    if settings.evaluate_require_idempotency_key:
        idem = (request.headers.get("Idempotency-Key") or request.headers.get("idempotency-key") or "").strip()
        if not idem:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "evaluate_idempotency_required",
                    "message": "Idempotency-Key header is required when TARKA_EVALUATE_REQUIRE_IDEMPOTENCY_KEY is enabled.",
                },
            )

    http = _http(request)
    trace_id = uuid.uuid4()
    replay_ttl_seconds = int(os.environ.get("REPLAY_PAYLOAD_TTL_SECONDS", "300"))
    degrade_tags: list[str] = []
    tenant_flags: dict[str, Any] = {}
    if redis_tags._client:
        try:
            tenant_flags = await redis_tags.get_tenant_flags(body.tenant_id)
        except Exception:
            tenant_flags = {}

    # Extract SDK signal tags
    dc_dump = body.device_context.model_dump() if body.device_context else None
    signal_tags = extract_signal_tags(dc_dump)
    signal_tags.extend(extract_behavior_tags(dc_dump))
    signal_tags.extend(extract_captcha_tags(dc_dump))
    consortium_delta = 0.0
    graph_delta = 0.0
    external_signal_delta = 0.0
    external_signal_meta: dict[str, Any] | None = None
    replay_rule_hits: list[str] = []

    # Detect payload replay at ingress using a short-lived signature cache.
    replay_signature = hashlib.sha256(
        _json.dumps(
            {
                "tenant_id": body.tenant_id,
                "event_type": body.event_type.value,
                "entity_id": body.entity_id,
                "session_id": body.session_id,
                "payload": body.payload,
                "device_id": body.device_context.device_id if body.device_context else None,
            },
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    is_replayed = await redis_tags.check_and_store_replay_signature(body.tenant_id, replay_signature, ttl_seconds=replay_ttl_seconds)
    if is_replayed:
        signal_tags.append("ingress:replay_payload")
        replay_rule_hits.append("ingress_replay_detected")

    # Record fingerprint & detect shared devices
    if body.device_context and fingerprint_store._client:
        fp_record = await fingerprint_store.record_fingerprint(
            body.tenant_id,
            body.device_context.model_dump(),
            body.entity_id,
        )
        if len(fp_record.entity_ids) > 1:
            signal_tags.append("sdk:shared_device")

    # Server-side entity ↔ device ↔ vendor ID linking (Redis)
    if body.device_context and entity_link_store._client:
        dc = body.device_context
        await entity_link_store.record_device_entity_link(
            body.tenant_id,
            dc.device_id,
            body.entity_id,
        )
        if isinstance(body.metadata, dict) and body.metadata:
            await entity_link_store.record_vendor_bridge(body.tenant_id, body.entity_id, body.metadata)

    # Check whitelist/blacklist/test bypass BEFORE full evaluation (bounded list step #32)
    list_check = None
    step_trace: list[dict[str, Any]] = []

    async def _list_check_call():
        return await _list_check_with_circuit(body.tenant_id, body.entity_id, degrade_tags, tenant_flags)

    list_check, list_trace = await run_evaluation_step(
        "list",
        _list_check_call,
        timeout_seconds=settings.eval_step_list_timeout_seconds,
        max_attempts=settings.eval_step_list_max_attempts,
        on_failure="SKIP",
        fallback=None,
    )
    step_trace.append(list_trace)

    if list_check and list_check.found:
        if list_check.action == "allow":
            _wl_inf = build_inference_context([], ["whitelist_bypass"], None, 0.0, None, **_infer_ctx_kwargs(body, {}))
            _wl_rec, _wl_meta = apply_challenge_policy(
                body.challenge_policy_id,
                None,
                "allow",
                _wl_inf,
                ["list:whitelist"],
                body.payload,
            )
            audit = AuditRecord(
                trace_id=trace_id,
                tenant_id=body.tenant_id,
                entity_id=body.entity_id,
                event_type=body.event_type.value,
                decision="allow",
                score=0.0,
                tags=["list:whitelist"],
                rule_hits=["whitelist_bypass"],
                payload_snapshot={
                    "whitelisted": True,
                    "reason": list_check.reason,
                    "inference_context": _wl_inf,
                    "recommended_action": _wl_rec,
                    "challenge_metadata": _wl_meta,
                    "step_trace": step_trace,
                    "counter_version": _audit_counter_version_label(),
                    "rule_pack_file": "",
                    "ml_model": _wl_inf.get("ml_model"),
                    **({"etl_batch_id": _eb_wl} if (_eb_wl := _metadata_etl_batch_id(body)) else {}),
                    "canary_cohort": build_canary_cohort_audit(
                        body.tenant_id,
                        body.entity_id,
                        salt_version=settings.policy_cohort_salt,
                        experiment_id=settings.policy_experiment_id or None,
                    ),
                },
            )
            session.add(audit)
            await session.commit()
            return EvaluateResponse(
                trace_id=trace_id,
                decision="allow",
                score=0.0,
                tags=["list:whitelist"],
                rule_hits=["whitelist_bypass"],
                reasons=[f"whitelist:{list_check.reason}"],
                ml_score=None,
                inference_context=_wl_inf,
                recommended_action=_wl_rec,
                challenge_policy_id=_wl_meta.get("policy_id"),
                challenge_metadata=_wl_meta,
            )

        if list_check.action == "deny":
            _bl_inf = build_inference_context(["list:blacklist"], ["blacklist_block"], None, 100.0, None, **_infer_ctx_kwargs(body, {}))
            _bl_base = derive_recommended_action("deny", ["list:blacklist"], _bl_inf)
            _bl_rec, _bl_meta = apply_challenge_policy(
                body.challenge_policy_id,
                _bl_base,
                "deny",
                _bl_inf,
                ["list:blacklist"],
                body.payload,
            )
            audit = AuditRecord(
                trace_id=trace_id,
                tenant_id=body.tenant_id,
                entity_id=body.entity_id,
                event_type=body.event_type.value,
                decision="deny",
                score=100.0,
                tags=["list:blacklist"],
                rule_hits=["blacklist_block"],
                payload_snapshot={
                    "blacklisted": True,
                    "reason": list_check.reason,
                    "inference_context": _bl_inf,
                    "recommended_action": _bl_rec,
                    "challenge_metadata": _bl_meta,
                    "step_trace": step_trace,
                    "counter_version": _audit_counter_version_label(),
                    "rule_pack_file": "",
                    "ml_model": _bl_inf.get("ml_model"),
                    **({"etl_batch_id": _eb_bl} if (_eb_bl := _metadata_etl_batch_id(body)) else {}),
                    "canary_cohort": build_canary_cohort_audit(
                        body.tenant_id,
                        body.entity_id,
                        salt_version=settings.policy_cohort_salt,
                        experiment_id=settings.policy_experiment_id or None,
                    ),
                },
            )
            session.add(audit)
            await session.commit()
            return EvaluateResponse(
                trace_id=trace_id,
                decision="deny",
                score=100.0,
                tags=["list:blacklist"],
                rule_hits=["blacklist_block"],
                reasons=[f"blacklist:{list_check.reason}"],
                ml_score=None,
                inference_context=_bl_inf,
                recommended_action=_bl_rec,
                challenge_policy_id=_bl_meta.get("policy_id"),
                challenge_metadata=_bl_meta,
            )

    async with acquire_eval_capacity(request.app) as cap:
        _dag = EvalDAGRuntime(load_shed=cap.load_shed)
        if cap.load_shed:
            try:
                get_metrics().inc("tarka_load_shedding_eval_total")
            except Exception:
                pass
        existing_tags = await redis_tags.get_tags(body.tenant_id, body.entity_id)
    
        if settings.consortium_enabled:
            try:
                signal_hash = hash_entity_id(
                    settings.consortium_secret,
                    body.tenant_id,
                    body.entity_id,
                    hash_scope=settings.consortium_hash_scope,
                )
                consortium_data = await redis_tags.check_consortium_signal(settings.consortium_id, signal_hash)
                consortium_delta = consortium_score_delta(
                    consortium_data,
                    min_tenants=settings.consortium_min_tenants,
                    min_reports=settings.consortium_min_reports,
                    trust_floor=settings.consortium_score_trust_floor,
                    max_delta=settings.consortium_score_max_delta,
                )
                if consortium_delta > 0:
                    signal_tags.append("consortium:cross_tenant_hit")
            except Exception:
                consortium_delta = 0.0
    
        # Graph routing (OSS #42): choose whether to call graph-service and which checkpoint to use.
        graph_checkpoint = _graph_checkpoint_from_body(body)
        graph_routing: dict[str, Any] | None = None
        if not graph_checkpoint:
            # Only apply routing policy when the caller has not pinned a checkpoint explicitly.
            # Base score here is pre-graph: JSON rules + consortium + replay, no graph_delta yet.
            tentative_base = 10.0 + consortium_delta + (20.0 if is_replayed else 0.0)
            graph_routing = decide_graph_routing(body.event_type.value, tentative_base, tags=signal_tags)
            if graph_routing and graph_routing.get("graph_checkpoint"):
                graph_checkpoint = str(graph_routing["graph_checkpoint"])
    
        graph_risk = None
        graph_trace = {"step": "graph_risk", "status": "skipped", "reason": "graph_routing_skip"}
        if _dag.include_graph():
            if not graph_routing or not graph_routing.get("skip_graph", False):
                graph_risk, graph_trace = await run_evaluation_step(
                    "graph_risk",
                    lambda: _fetch_graph_risk_wrapped(
                        http,
                        body.tenant_id,
                        body.entity_id,
                        degrade_tags,
                        tenant_flags,
                        graph_checkpoint,
                    ),
                    timeout_seconds=settings.eval_step_graph_risk_timeout_seconds,
                    max_attempts=settings.eval_step_graph_risk_max_attempts,
                    on_failure="SKIP",
                    fallback=None,
                )
                if graph_risk:
                    graph_delta = graph_score_delta(graph_risk.get("risk_score"))
                    signal_tags.extend(graph_tags_from_risk(graph_risk))
        else:
            graph_trace = {"step": "graph_risk", "status": "skipped", "reason": "load_shedding"}
            if "load_shedding:active" not in degrade_tags:
                degrade_tags.append("load_shedding:active")
            try:
                get_metrics().inc("tarka_load_shedding_active_total")
            except Exception:
                pass
        step_trace.append(graph_trace)
    
        # Feature snapshot (needed before OPA)
        snapshot, snap_trace = await run_evaluation_step(
            "feature_snapshot",
            lambda: _fetch_feature_snapshot_wrapped(http, body, existing_tags, degrade_tags, tenant_flags),
            timeout_seconds=settings.eval_step_feature_snapshot_timeout_seconds,
            max_attempts=settings.eval_step_feature_snapshot_max_attempts,
            on_failure="SKIP",
            fallback=_feature_snapshot_fallback(body, existing_tags),
        )
        step_trace.append(snap_trace)
        features: dict[str, Any] = dict(snapshot.get("features") or {})
        redis_tag_list = list(snapshot.get("redis_tags") or existing_tags)
    
        # Entity linking hints for rules (device ↔ entities, optional vendor bridge)
        if body.device_context and entity_link_store._client:
            linked = await entity_link_store.get_entities_for_device(
                body.tenant_id,
                body.device_context.device_id,
                limit=50,
            )
            others = [e for e in linked if e != body.entity_id]
            if others:
                features["linked_entity_ids"] = others[:20]
                signal_tags.append("sdk:linked_entities")
            if isinstance(body.metadata, dict):
                for vtype, mkey in (("visitor", "vendor_visitor_id"), ("device", "vendor_device_id"), ("install", "vendor_install_id")):
                    vid = body.metadata.get(mkey)
                    if isinstance(vid, str) and vid.strip():
                        bridged = await entity_link_store.get_entity_for_vendor(body.tenant_id, vtype, vid.strip())
                        if bridged and bridged != body.entity_id:
                            features["vendor_bridge_entity_id"] = bridged
                            signal_tags.append("sdk:vendor_entity_bridge")
                        break
    
        # Merge device signals into features so rules engine can see them
        if body.device_context:
            for k, v in body.device_context.signals.items():
                features.setdefault(k, v)
        if body.session_id:
            features.setdefault("session_id", body.session_id)
    
        if body.agent_context is not None:
            features["agent_context"] = body.agent_context.model_dump(mode="json", exclude_none=True)
    
        # Normalise amount to USD if a currency is specified
        payload_currency = body.payload.get("currency")
        if payload_currency and "amount" in body.payload:
            try:
                original_amount = float(body.payload["amount"])
                normalized = await normalize_amount(original_amount, payload_currency, "USD", http)
                features["amount"] = normalized
                features["original_amount"] = original_amount
                features["original_currency"] = payload_currency
            except (TypeError, ValueError):
                pass
    
        # Counter ownership: prefer counter-service as source of truth; keep local aggregates as fallback.
        counter_meta: dict[str, Any] | None = None
        if settings.counter_service_url:
            counter_meta, counter_trace = await run_evaluation_step(
                "counter_snapshot",
                lambda: _fetch_counter_snapshot_wrapped(http, body, features, degrade_tags),
                timeout_seconds=settings.eval_step_feature_snapshot_timeout_seconds,
                max_attempts=settings.eval_step_feature_snapshot_max_attempts,
                on_failure="SKIP",
                fallback=None,
            )
            step_trace.append(counter_trace)
            if isinstance(counter_meta, dict):
                counters = counter_meta.get("counters")
                if isinstance(counters, dict):
                    features.update(counters)
                if counter_meta.get("definition_id"):
                    features["counter_definition_id"] = counter_meta.get("definition_id")
                if counter_meta.get("definition_version") is not None:
                    features["counter_definition_version"] = counter_meta.get("definition_version")
            elif agg_store._client:
                # Adapter shim while services roll out; keeps evaluate path functional during outages.
                degrade_tags.append("counter:fallback_local_agg")
                agg_features = await agg_store.compute_features(body.tenant_id, body.entity_id, features)
                features.update(agg_features)
                agg_ts = event_time_unix_for_evaluate(body.metadata, body.payload)
                await agg_store.record_event(body.tenant_id, body.entity_id, str(trace_id), features, ts=agg_ts)
        elif agg_store._client:
            agg_features = await agg_store.compute_features(body.tenant_id, body.entity_id, features)
            features.update(agg_features)
            # Record this event for future aggregate computation (uses normalised amount).
            # Optional metadata.event_time / payload.event_time sets Redis scores to business time (late arrival).
            agg_ts = event_time_unix_for_evaluate(body.metadata, body.payload)
            await agg_store.record_event(body.tenant_id, body.entity_id, str(trace_id), features, ts=agg_ts)
    
        geo_extra_tags: list[str] = []
        if body.device_context:
            geo_extra_tags = merge_session_geo_from_device_and_features(features)
            for t in geo_extra_tags:
                if t == "sdk:geo_ip_mismatch":
                    features["geo_ip_mismatch"] = True
                elif t == "sdk:geo_tz_mismatch":
                    features["geo_tz_mismatch"] = True
            signal_tags.extend(geo_extra_tags)
    
        location_meta: dict[str, Any] | None = None
        if settings.location_service_url:
            location_meta, location_trace = await run_evaluation_step(
                "location_eval",
                lambda: _fetch_location_evaluation_wrapped(http, body, features, degrade_tags),
                timeout_seconds=settings.eval_step_feature_snapshot_timeout_seconds,
                max_attempts=settings.eval_step_feature_snapshot_max_attempts,
                on_failure="SKIP",
                fallback=None,
            )
            step_trace.append(location_trace)
            if isinstance(location_meta, dict):
                try:
                    features["geo_consistency_risk"] = float(location_meta.get("geo_consistency_risk"))
                except (TypeError, ValueError):
                    pass
                try:
                    features["copresence_risk"] = float(location_meta.get("copresence_risk"))
                except (TypeError, ValueError):
                    pass
                try:
                    features["impossible_travel_risk"] = float(location_meta.get("impossible_travel_risk"))
                except (TypeError, ValueError):
                    pass
                ltags = location_meta.get("tags")
                if isinstance(ltags, list):
                    signal_tags.extend(str(t) for t in ltags if isinstance(t, str))
    
        external_signal_meta, external_trace = await run_evaluation_step(
            "external_signals",
            lambda: _fetch_external_signals_wrapped(http, body, features, degrade_tags),
            timeout_seconds=settings.external_signal_timeout_seconds,
            max_attempts=settings.eval_step_external_signal_max_attempts,
            on_failure="SKIP",
            fallback=None,
        )
        step_trace.append(external_trace)
        if isinstance(external_signal_meta, dict):
            try:
                external_signal_delta = max(0.0, min(20.0, float(external_signal_meta.get("score_delta", 0.0))))
            except (TypeError, ValueError):
                external_signal_delta = 0.0
            ext_tags = external_signal_meta.get("tags")
            if isinstance(ext_tags, list):
                signal_tags.extend(str(t) for t in ext_tags if isinstance(t, str))
            ext_enrichment = external_signal_meta.get("enrichments")
            if isinstance(ext_enrichment, dict):
                features.setdefault("external_signals", {})
                if isinstance(features["external_signals"], dict):
                    features["external_signals"].update(ext_enrichment)
    
        # Platform integrity supplements (must run before JSON tag_rules so policy can match integrity:*)
        _plat_kw = _infer_ctx_kwargs(body, features)
        signal_tags.extend(supplemental_tags_for_integrity(_plat_kw["platform"], signal_tags))
    
        # Run rules + OPA + ML in parallel (OPA and ML don't need each other)
        rule_hits, rule_tags, score_delta, json_rule_pack_files = evaluate_json_rules(
            features,
            redis_tag_list,
            body.tenant_id,
            body.entity_id,
            evaluation_mode="production",
            signal_tags=signal_tags,
        )
    
        opa_task = run_evaluation_step(
            "opa",
            lambda: _evaluate_opa_wrapped(http, snapshot, degrade_tags, tenant_flags),
            timeout_seconds=settings.eval_step_opa_timeout_seconds,
            max_attempts=settings.eval_step_opa_max_attempts,
            on_failure="SKIP",
            fallback=None,
        )
        if _dag.include_ml(snap_trace):
            ml_task = run_evaluation_step(
                "ml_score",
                lambda: _fetch_ml_score_wrapped(
                    http,
                    body.tenant_id,
                    body.entity_id,
                    body.event_type.value,
                    features,
                    degrade_tags,
                    tenant_flags,
                ),
                timeout_seconds=settings.eval_step_ml_timeout_seconds,
                max_attempts=settings.eval_step_ml_max_attempts,
                on_failure="SKIP",
                fallback=(None, {}),
            )
            (opa_result, opa_trace), (ml_pack, ml_trace) = await asyncio.gather(opa_task, ml_task, return_exceptions=False)
        else:
            opa_result, opa_trace = await opa_task
            ml_pack = (None, {})
            ml_trace = {
                "step": "ml_score",
                "status": "skipped",
                "reason": _dag.ml_skip_reason(snap_trace),
                "attempts": 0,
            }
        step_trace.extend([opa_trace, ml_trace])
        ml_score, ml_detail = ml_pack
    
        for _dt in degrade_tags:
            if _dt not in signal_tags:
                signal_tags.append(_dt)
    
        opa_delta = 0.0
        if opa_result and isinstance(opa_result, dict):
            rule_hits.extend(str(x) for x in opa_result.get("rule_hits", []))
            rule_tags.extend(str(t) for t in opa_result.get("tags", []))
            opa_delta = float(opa_result.get("score_delta", 0))
            score_delta += opa_delta
    
        policy_routing: dict[str, Any] | None = None
        if settings.policy_champion_challenger_enabled:
            _, _, ch_json_delta, _ = evaluate_json_rules(
                features,
                redis_tag_list,
                body.tenant_id,
                body.entity_id,
                evaluation_mode="challenger",
                signal_tags=signal_tags,
            )
            replay_delta_cc = 20.0 if is_replayed else 0.0
            champion_rule_score = 10.0 + score_delta + consortium_delta + graph_delta + replay_delta_cc
            challenger_rule_score = 10.0 + ch_json_delta + opa_delta + consortium_delta + graph_delta + replay_delta_cc
            policy_routing = build_policy_routing_audit(
                cohort_bucket=cohort_bucket_0_99(body.tenant_id, body.entity_id, settings.policy_cohort_salt),
                cohort_salt=settings.policy_cohort_salt,
                champion_rule_score=champion_rule_score,
                challenger_rule_score=challenger_rule_score,
                champion_decision=decision_from_rule_score(champion_rule_score),
                challenger_decision=decision_from_rule_score(challenger_rule_score),
                ml_score=ml_score if isinstance(ml_score, float) else None,
            )
    
        signal_tags.extend(
            derive_contextual_tags(
                features=features,
                signal_tags=signal_tags,
                graph_risk=graph_risk if isinstance(graph_risk, dict) else None,
                external_signal_meta=external_signal_meta if isinstance(external_signal_meta, dict) else None,
            )
        )
    
        all_new_tags = rule_tags + signal_tags
        if consortium_delta > 0:
            rule_hits.append("consortium_shared_signal")
        if graph_delta > 0:
            rule_hits.append("graph_network_risk")
        if external_signal_delta > 0:
            rule_hits.append("external_signal_risk")
        replay_delta = 20.0 if is_replayed else 0.0
        base_score = 10.0 + score_delta + consortium_delta + graph_delta + replay_delta + external_signal_delta
        final_score = _blend_scores(base_score, ml_score if isinstance(ml_score, float) else None)
    
        calibration_meta: dict[str, Any] | None = None
        if settings.calibration_service_url:
            if _dag.include_calibration(opa_trace, ml_trace):
                baseline_inf = build_inference_context(
                    list(dict.fromkeys(signal_tags)),
                    rule_hits + replay_rule_hits,
                    ml_score if isinstance(ml_score, float) else None,
                    final_score,
                    features,
                    ml_detail=ml_detail if isinstance(ml_detail, dict) else None,
                    location_meta=location_meta,
                    counter_meta=counter_meta,
                    graph_meta=graph_risk if isinstance(graph_risk, dict) else None,
                    external_signal_meta=external_signal_meta if isinstance(external_signal_meta, dict) else None,
                    policy_experiment_id=settings.policy_experiment_id or None,
                    **_plat_kw,
                )
                baseline_conf = float(baseline_inf.get("integrity_confidence") or 0.0)
                calibration_meta, calibration_trace = await run_evaluation_step(
                    "calibration_adjustment",
                    lambda: _fetch_calibration_adjustment_wrapped(http, body, baseline_conf, features, degrade_tags),
                    timeout_seconds=settings.eval_step_feature_snapshot_timeout_seconds,
                    max_attempts=settings.eval_step_feature_snapshot_max_attempts,
                    on_failure="SKIP",
                    fallback=None,
                )
                step_trace.append(calibration_trace)
                if isinstance(calibration_meta, dict):
                    cal_conf = calibration_meta.get("calibrated_confidence")
                    if isinstance(cal_conf, (float, int)):
                        features["calibrated_integrity_confidence"] = float(cal_conf)
                    profile_id = calibration_meta.get("profile_id")
                    if isinstance(profile_id, str) and profile_id.strip():
                        features["calibration_profile"] = profile_id.strip()
                    expected_ver = calibration_meta.get("expected_calibration_version")
                    try:
                        if expected_ver is not None:
                            features["expected_calibration_version"] = int(expected_ver)
                    except (TypeError, ValueError):
                        pass
            else:
                reason = "load_shedding" if _dag.load_shed else "skipped_due_to_dependency_failure"
                step_trace.append(
                    {"step": "calibration_adjustment", "status": "skipped", "reason": reason, "attempts": 0}
                )
    
        merged_tags = await redis_tags.merge_tags(body.tenant_id, body.entity_id, all_new_tags)
        await redis_tags.set_cached_score(body.tenant_id, body.entity_id, final_score)
    
        combined_rule_hits = rule_hits + replay_rule_hits
    
        typology_results = evaluate_typologies(combined_rule_hits, features)
        typology_summary = summarize_typologies(typology_results)
    
        if final_score >= settings.deny_threshold:
            decision = "deny"
        elif final_score >= settings.review_threshold:
            decision = "review"
        else:
            decision = "allow"
    
        reasons: list[str] = []
        if combined_rule_hits:
            reasons.append(f"rules:{','.join(combined_rule_hits)}")
        if signal_tags:
            reasons.append(f"signals:{','.join(signal_tags)}")
        if ml_score is not None and isinstance(ml_score, float):
            reasons.append(f"ml:{ml_score:.2f}")
        if external_signal_delta > 0:
            reasons.append(f"external_signals:+{external_signal_delta:.2f}")
    
        merged_signal_tags = list(dict.fromkeys(signal_tags))
        inf_ctx = build_inference_context(
            merged_signal_tags,
            combined_rule_hits,
            ml_score if isinstance(ml_score, float) else None,
            final_score,
            features,
            ml_detail=ml_detail if isinstance(ml_detail, dict) else None,
            calibration_meta=calibration_meta,
            counter_meta=counter_meta,
            location_meta=location_meta,
            graph_meta=graph_risk if isinstance(graph_risk, dict) else None,
            external_signal_meta=external_signal_meta if isinstance(external_signal_meta, dict) else None,
            policy_experiment_id=settings.policy_experiment_id or None,
            **_plat_kw,
        )
        recommended_action = derive_recommended_action(decision, merged_signal_tags, inf_ctx)
        recommended_action, ch_meta = apply_challenge_policy(
            body.challenge_policy_id,
            recommended_action,
            decision,
            inf_ctx,
            merged_tags,
            body.payload,
        )
    
        graph_decision_explanation = build_graph_decision_explanation_v1(
            trace_id=str(trace_id),
            tenant_id=body.tenant_id,
            entity_id=body.entity_id,
            graph_risk=graph_risk if isinstance(graph_risk, dict) else None,
            graph_trace=graph_trace if isinstance(graph_trace, dict) else None,
        )
    
        # Apply region-aware PII masking before storage
        region = getattr(body, "region", settings.default_region) or settings.default_region
        privacy_profile = get_profile(region)
        raw_snapshot: dict[str, Any] = {"payload": body.payload, "metadata": body.metadata}
        if body.agent_context is not None:
            raw_snapshot["agent_context"] = body.agent_context.model_dump(mode="json", exclude_none=True)
        if privacy_profile.mask_pii_in_logs or privacy_profile.pseudonymize_at_rest:
            stored_snapshot = mask_dict(raw_snapshot, privacy_profile)
        else:
            stored_snapshot = raw_snapshot
    
        fb_reason = _compute_fallback_reason(degrade_tags, step_trace)
        snap_extra: dict[str, Any] = {
            **stored_snapshot,
            "inference_context": inf_ctx,
            "recommended_action": recommended_action,
            "challenge_metadata": ch_meta,
            "step_trace": step_trace,
            "typologies": typology_results,
            "typology_summary": typology_summary,
            "canary_cohort": build_canary_cohort_audit(
                body.tenant_id,
                body.entity_id,
                salt_version=settings.policy_cohort_salt,
                experiment_id=settings.policy_experiment_id or None,
            ),
        }
        if graph_checkpoint:
            snap_extra["graph_checkpoint"] = graph_checkpoint
        if graph_routing is not None:
            snap_extra["graph_routing"] = graph_routing
        if fb_reason:
            snap_extra["fallback_reason"] = fb_reason
        if policy_routing is not None:
            snap_extra["policy_routing"] = policy_routing
        if calibration_meta is not None:
            snap_extra["calibration"] = calibration_meta
        if counter_meta is not None:
            snap_extra["counter"] = counter_meta
        if location_meta is not None:
            snap_extra["location"] = location_meta
        if external_signal_meta is not None:
            snap_extra["external_signals"] = external_signal_meta
        if graph_decision_explanation is not None:
            snap_extra["graph_decision_explanation"] = graph_decision_explanation
    
        snap_extra["counter_version"] = _audit_counter_version_label()
        snap_extra["rule_pack_file"] = ",".join(json_rule_pack_files)
        snap_extra["ml_model"] = inf_ctx.get("ml_model")
        _eb_snap = _metadata_etl_batch_id(body)
        if _eb_snap:
            snap_extra["etl_batch_id"] = _eb_snap
    
        audit = AuditRecord(
            trace_id=trace_id,
            tenant_id=body.tenant_id,
            entity_id=body.entity_id,
            event_type=body.event_type.value,
            decision=decision,
            score=final_score,
            tags=merged_tags,
            rule_hits=combined_rule_hits,
            payload_snapshot=snap_extra,
        )
        session.add(audit)
        await session.commit()
    
        decision_log_record = build_decision_log_record(
            trace_id=str(trace_id),
            tenant_id=body.tenant_id,
            entity_id=body.entity_id,
            event_type=body.event_type.value,
            decision=decision,
            score=final_score,
            tags=merged_tags,
            rule_hits=combined_rule_hits,
            reasons=reasons,
            ml_score=ml_score if isinstance(ml_score, float) else None,
            inference_context=inf_ctx,
            recommended_action=recommended_action,
            challenge_policy_id=ch_meta.get("policy_id"),
            challenge_metadata=ch_meta,
            fallback_reason=fb_reason,
            payload_snapshot=snap_extra,
            artifact_manifest=_build_artifact_manifest(
                json_rule_pack_files=json_rule_pack_files,
                inf_ctx=inf_ctx,
                graph_checkpoint=graph_checkpoint,
                external_signal_meta=external_signal_meta if isinstance(external_signal_meta, dict) else None,
                challenge_policy_id=ch_meta.get("policy_id"),
            ),
        )
        bg.add_task(emit_decision_log, decision_log_record)
    
        bg.add_task(_graph_upsert_stepped, http, body, str(trace_id), merged_tags, geo_extra_tags, tenant_flags)
    
        try:
            m = get_metrics()
            m.inc(f"fraud_decisions_{decision}_total")
            m.inc("fraud_evaluations_total")
            if fb_reason:
                m.inc("fraud_fallback_total")
                reason_key = _re.sub(r"[^a-zA-Z0-9_]+", "_", str(fb_reason)).strip("_").lower()[:64]
                if reason_key:
                    m.inc(f"fraud_fallback_total_{reason_key}")
            if signal_tags:
                for st in signal_tags:
                    m.inc(f"fraud_signal_tag_{st}_total")
        except Exception:
            pass
    
        response_tier = _resolve_response_explainability_tier(request)
        response_inf_ctx = _shape_inference_context_for_tier(inf_ctx, response_tier)
        region_profile = get_profile(body.region)
        if region_profile.mask_pii_in_responses:
            response_inf_ctx = mask_dict(response_inf_ctx, region_profile)
    
        response_graph_explanation = graph_decision_explanation
        if response_graph_explanation is not None and region_profile.mask_pii_in_responses:
            response_graph_explanation = mask_dict(response_graph_explanation, region_profile)
    
        response = EvaluateResponse(
            trace_id=trace_id,
            decision=decision,
            score=final_score,
            tags=merged_tags,
            rule_hits=combined_rule_hits,
            reasons=reasons,
            ml_score=ml_score if isinstance(ml_score, float) else None,
            inference_context=response_inf_ctx,
            recommended_action=recommended_action,
            challenge_policy_id=ch_meta.get("policy_id"),
            challenge_metadata=ch_meta,
            fallback_reason=fb_reason,
            graph_decision_explanation=response_graph_explanation,
        )
    
        bg.add_task(
            _broadcast_decision,
            {
                "trace_id": str(trace_id),
                "tenant_id": body.tenant_id,
                "entity_id": body.entity_id,
                "event_type": body.event_type.value,
                "decision": decision,
                "score": final_score,
                "tags": merged_tags,
            },
        )
    
        bg.add_task(
            _publish_decision,
            request.app.state,
            {
                "trace_id": str(trace_id),
                "tenant_id": body.tenant_id,
                "entity_id": body.entity_id,
                "event_type": body.event_type.value,
                "decision": decision,
                "score": final_score,
                "tags": merged_tags,
                "rule_hits": combined_rule_hits,
                "signal_tags": signal_tags,
                "ml_score": ml_score if isinstance(ml_score, float) else None,
                "payload": body.payload,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    
        bg.add_task(
            _run_shadow_evaluation,
            request.app.state,
            features,
            redis_tag_list,
            decision,
            final_score,
            body.tenant_id,
            str(trace_id),
        )
    
        # Test bypass: run full evaluation but override decision to allow
        if list_check and list_check.found and list_check.list_type == "test_bypass":
            _tb_hits = combined_rule_hits + ["test_bypass"]
            _tb_plat = _infer_ctx_kwargs(body, features)
            _tb_extra = supplemental_tags_for_integrity(_tb_plat["platform"], signal_tags)
            _tb_merged = list(dict.fromkeys(signal_tags + _tb_extra))
            _tb_inf = build_inference_context(
                _tb_merged,
                _tb_hits,
                ml_score if isinstance(ml_score, float) else None,
                final_score,
                features,
                ml_detail=ml_detail if isinstance(ml_detail, dict) else None,
                **_tb_plat,
            )
            _tb_base = derive_recommended_action("allow", _tb_merged, _tb_inf)
            _tb_rec, _tb_meta = apply_challenge_policy(
                body.challenge_policy_id,
                _tb_base,
                "allow",
                _tb_inf,
                signal_tags,
                body.payload,
            )
            response = EvaluateResponse(
                trace_id=trace_id,
                decision="allow",
                score=final_score,
                tags=merged_tags + ["list:test_bypass"],
                rule_hits=_tb_hits,
                reasons=reasons + [f"test_bypass:{list_check.reason}"],
                ml_score=ml_score if isinstance(ml_score, float) else None,
                inference_context=_tb_inf,
                recommended_action=_tb_rec,
                challenge_policy_id=_tb_meta.get("policy_id"),
                challenge_metadata=_tb_meta,
                fallback_reason=fb_reason,
            )
    
    return response


# ---------- websocket ----------


@app.websocket("/v1/decisions/ws")
async def ws_decision_feed(ws: WebSocket):
    """Live stream of fraud decisions for dashboards."""
    tenant_id = (ws.query_params.get("tenant_id") or "").strip()
    if not tenant_id:
        await ws.close(code=4400, reason="tenant_id query parameter is required")
        return
    keys = _get_api_keys()
    if keys:
        key = (ws.headers.get("x-api-key") or "").strip()
        if key not in keys:
            await ws.close(code=4401, reason="invalid or missing API key")
            return
        tenant_map = parse_api_key_tenant_map()
        if tenant_map:
            allowed = tenant_map.get(key, set())
            if "*" not in allowed and tenant_id not in allowed:
                await ws.close(code=4403, reason="tenant out of scope")
                return
    else:
        allow = os.environ.get("ALLOW_INSECURE_NO_AUTH", "").strip().lower() in {"1", "true", "yes", "on"}
        if not allow:
            await ws.close(code=4401, reason="authentication required")
            return
    await ws.accept()
    _ws_clients[ws] = tenant_id
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        _ws_clients.pop(ws, None)


# ---------- rule builder UI ----------
from pathlib import Path as _Path  # noqa: E402

from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

_STATIC_DIR = _Path(__file__).resolve().parent.parent.parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/rules-ui", include_in_schema=False)
    async def rules_ui():
        return FileResponse(_STATIC_DIR / "rule-builder.html")

    @app.get("/dashboard", include_in_schema=False)
    async def dashboard_ui():
        return FileResponse(_STATIC_DIR / "dashboard.html")


@app.get("/v1/audit/{trace_id}")
async def get_audit(
    trace_id: UUID,
    request: Request,
    tenant_id: str = Query(..., description="Must match the audit row tenant_id"),
    detail_level: str = Query("minimal", pattern="^(minimal|analyst|full)$"),
    session: AsyncSession = Depends(get_session),
):
    user = getattr(request.state, "auth_user", None)
    if detail_level in {"analyst", "full"} and not (user and hasattr(user, "has_role") and user.has_role("analyst")):
        raise HTTPException(status_code=403, detail="analyst role required for full audit detail")
    result = await session.execute(select(AuditRecord).where(AuditRecord.trace_id == trace_id))
    row = result.scalar_one_or_none()
    if not row or str(row.tenant_id) != tenant_id:
        raise HTTPException(status_code=404, detail="not found")
    snap = row.payload_snapshot or {}
    inf_ctx = snap.get("inference_context")
    if not isinstance(inf_ctx, dict):
        inf_ctx = {}
    inf_ctx_out = _shape_inference_context_for_tier(inf_ctx, detail_level)
    out: dict[str, Any] = {
        "trace_id": str(row.trace_id),
        "tenant_id": row.tenant_id,
        "entity_id": row.entity_id,
        "event_type": row.event_type,
        "decision": row.decision,
        "score": row.score,
        "tags": row.tags,
        "rule_hits": row.rule_hits,
        "counter_version": snap.get("counter_version"),
        "rule_pack_file": snap.get("rule_pack_file"),
        "ml_model": snap.get("ml_model"),
        "etl_batch_id": snap.get("etl_batch_id"),
        "inference_context": inf_ctx_out,
        "decision_explain": {
            "driver_reasons": inf_ctx_out.get("driver_reasons", []),
            "driver_explain": inf_ctx_out.get("driver_explain", []),
        },
        "recommended_action": snap.get("recommended_action"),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
    ge = snap.get("graph_decision_explanation")
    if isinstance(ge, dict):
        out["graph_decision_explanation"] = ge
    return out


@app.get("/v1/analyst/entity-velocity")
async def analyst_entity_velocity(
    tenant_id: str = Query(..., min_length=1, max_length=128),
    entity_id: str = Query(..., min_length=1, max_length=512),
):
    """Redis-backed event counts + velocity slice of inference_context for investigations (read-only)."""
    eid = str(entity_id).strip()
    tid = str(tenant_id).strip()
    if not _ANALYST_ENTITY_ID.match(eid):
        raise HTTPException(status_code=400, detail="invalid entity_id")
    try:
        raw_features = await agg_store.compute_features(tid, eid, {})
    except Exception as exc:
        log.warning("entity-velocity aggregates failed: %s", exc)
        raw_features = {f"event_count_{w}": 0 for w in ("5m", "1h", "24h", "7d")}
    inf = build_inference_context(
        signal_tags=[],
        rule_hits=[],
        ml_score=None,
        final_score=0.0,
        features=raw_features,
        platform="web",
    )
    vel_keys = ("event_count_5m", "event_count_1h", "event_count_24h", "event_count_7d")
    agg_slice = {k: raw_features.get(k, 0) for k in vel_keys}
    for k, v in sorted(raw_features.items()):
        if k.startswith("distinct_"):
            agg_slice[k] = v
    return {
        "entity_id": eid,
        "tenant_id": tid,
        "aggregate_features": agg_slice,
        "inference_velocity": {
            "velocity_events_5m": inf["velocity_events_5m"],
            "velocity_events_1h": inf["velocity_events_1h"],
            "velocity_events_24h": inf["velocity_events_24h"],
            "impossible_travel_risk": inf["impossible_travel_risk"],
            "colocation_risk": inf["colocation_risk"],
            "driver_reasons": [d for d in inf["driver_reasons"] if any(x in d for x in ("velocity", "travel", "device", "entity", "ml_score"))],
        },
        "anomaly_flags": _velocity_anomaly_flags(raw_features),
    }
