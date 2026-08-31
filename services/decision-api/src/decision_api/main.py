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
from typing import Any, Literal
from uuid import UUID

import httpx
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from decision_api.config import settings
from decision_api.deps import close_analytics_infra, open_analytics_infra

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
            "async_osint_redis": {
                "timeout_seconds": float(
                    os.environ.get("ASYNC_OSINT_REDIS_TIMEOUT_SECONDS", "0.08")
                ),
                "max_attempts": int(
                    os.environ.get("ASYNC_OSINT_REDIS_MAX_ATTEMPTS", "1")
                ),
                "circuit_failure_threshold": int(
                    os.environ.get("ASYNC_OSINT_REDIS_CIRCUIT_FAILURE_THRESHOLD", "5")
                ),
                "circuit_recovery_seconds": float(
                    os.environ.get("ASYNC_OSINT_REDIS_CIRCUIT_RECOVERY_SECONDS", "2.0")
                ),
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


from decision_api.db import get_session, init_db
from decision_api.entity_link_store import entity_link_store
from decision_api.eval_load_guard import EvalLoadGuard
from decision_api.eval_steps import run_evaluation_step
from decision_api.fingerprint_store import fingerprint_store
from decision_api.json_rules import (
    evaluate_json_rules,  # noqa: F401 — evaluate pipeline + tests patch via main
    load_rules,
)
from decision_api.json_rules import (
    governance_summary as rules_governance_summary,
)
from decision_api.models import AuditRecord
from decision_api.opa_client import apply_opa_unconfigured, evaluate_opa_or_raise
from decision_api.redis_store import redis_tags
from decision_api.retention import DEFAULT_RETENTION_DAYS, retention_loop

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared"))
from circuit import AsyncCircuitBreaker, CircuitOpenError  # noqa: E402
from entity_lists import ListCheckResult, create_list_store  # noqa: E402

from decision_api.aggregates import agg_store
from decision_api.attestation_taxonomy import attestation_signal_tags
from decision_api.challenge_policy import (
    load_challenge_policies,
)
from decision_api.inference_build import (
    SCHEMA_VERSION as INFERENCE_SCHEMA_VERSION,
)
from decision_api.inference_build import (
    build_inference_context,
)
from decision_api.lists_api import get_store as _get_list_store
from decision_api.lists_api import router as lists_router
from decision_api.lists_api import set_store
from decision_api.schemas import EvaluateRequest, EvaluateResponse
from decision_api.shadow import evaluate_shadow, load_shadow_rules, record_observation
from decision_api.tenant_flags import tenant_flag_enabled
from decision_api.trusted_zones import load_trusted_zones_for_tenant
from decision_api.typology import (
    load_typology_definitions,
    reload_typology_definitions,
    weighted_aggregation_telemetry,
)
from decision_api.typology_predicate_registry import (
    load_predicate_registry,
    registry_public_view,
    reload_predicate_registry,
)

# ---------- observability ----------
from auth_rbac import require_role, setup_auth  # noqa: E402
from observability import get_metrics, setup_observability  # noqa: E402
from rate_limiter import setup_rate_limiter  # noqa: E402
from security_headers import setup_security_headers  # noqa: E402
from tenant_binding import parse_api_key_tenant_map  # noqa: E402
from tarka_shared.tracing import setup_tracing  # noqa: E402

log = logging.getLogger("decision-api")

TENANT_CONFIG_UNAVAILABLE_DETAIL = "Tenant configuration unavailable"


def _metrics_inc_safe(metric: str, *, trace_id: uuid.UUID | None = None) -> None:
    """Increment a counter; log and continue when the metrics backend is unavailable."""
    try:
        get_metrics().inc(metric)
    except Exception as exc:
        log.warning(
            "decision_metrics_inc_failed metric=%s trace_id=%s error=%s",
            metric,
            trace_id,
            exc,
        )


async def _load_tenant_flags_for_evaluate(tenant_id: str) -> dict[str, Any]:
    """Load tenant feature flags; fail closed when Redis tag store lookup errors."""
    if not redis_tags.is_tag_store_available:
        return {}
    try:
        return await redis_tags.get_tenant_flags(tenant_id)
    except Exception as exc:
        log.exception("tenant_flags_lookup_failed tenant_id=%s", tenant_id)
        raise HTTPException(
            status_code=500,
            detail=TENANT_CONFIG_UNAVAILABLE_DETAIL,
        ) from exc


def _upstream_headers() -> dict[str, str]:
    """Shared auth headers for outbound service calls."""
    key = settings.upstream_api_key.strip() if settings.upstream_api_key.strip() else ""
    if not key:
        key = (
            settings.api_keys.split(",")[0].strip() if settings.api_keys.strip() else ""
        )
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


def _graph_routing_match_when(
    when: list[dict[str, Any]] | None, ctx: dict[str, Any]
) -> bool:
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
            if op == "eq" and lhs_v != rhs_v:
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
                result["graph_checkpoint"] = (
                    gc
                    if isinstance(gc, str) or gc is None
                    else result["graph_checkpoint"]
                )
            result["matched_rule_id"] = rule.get("id")
            break
    return result


def _circuit_metrics_inc(name: str) -> None:
    _metrics_inc_safe(name)


async def _list_check_with_circuit(
    tenant_id: str,
    entity_id: str,
    degrade_tags: list[str],
    tenant_flags: dict[str, Any],
) -> ListCheckResult:
    if tenant_flag_enabled(tenant_flags, "disable_entity_lists"):
        degrade_tags.append("lists:disabled_by_tenant")
        return ListCheckResult(
            found=False, action="evaluate", reason="tenant_flag_disable_entity_lists"
        )

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
    event_type: str | None = None,
) -> dict[str, Any] | None:
    from decision_api.evaluate.enrichment import fetch_graph_risk_wrapped

    return await fetch_graph_risk_wrapped(
        http,
        tenant_id,
        entity_id,
        degrade_tags,
        tenant_flags,
        graph_checkpoint,
        event_type,
    )


async def _fetch_feature_snapshot_wrapped(
    http: httpx.AsyncClient,
    body: EvaluateRequest,
    redis_tag_list: list[str],
    degrade_tags: list[str],
    tenant_flags: dict[str, Any],
) -> dict[str, Any]:
    from decision_api.evaluate.enrichment import fetch_feature_snapshot_wrapped

    return await fetch_feature_snapshot_wrapped(
        http, body, redis_tag_list, degrade_tags, tenant_flags
    )


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
    await _maybe_await(r.raise_for_status())
    data = await _maybe_await(r.json())
    return data if isinstance(data, dict) else None


async def _fetch_counter_snapshot_wrapped(
    http: httpx.AsyncClient,
    body: EvaluateRequest,
    features: dict[str, Any],
    degrade_tags: list[str],
) -> dict[str, Any] | None:
    from decision_api.evaluate.score import tag_hop_unconfigured

    if tag_hop_unconfigured(degrade_tags, "counter"):
        return None
    try:
        return await _circuit_counter.call(
            lambda: _fetch_counter_snapshot(http, body, features)
        )
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
        la = (
            float(features.get("session_last_lat"))
            if features.get("session_last_lat") is not None
            else None
        )
        lo = (
            float(features.get("session_last_lon"))
            if features.get("session_last_lon") is not None
            else None
        )
        lts = (
            float(features.get("session_last_ts"))
            if features.get("session_last_ts") is not None
            else None
        )
        if la is not None and lo is not None:
            current = {
                "lat": la,
                "lon": lo,
                "ts": lts,
                "source": str(features.get("geo_source_resolved") or "derived"),
            }
    except (TypeError, ValueError):
        current = None
    try:
        pla = (
            float(features.get("session_prev_lat"))
            if features.get("session_prev_lat") is not None
            else None
        )
        plo = (
            float(features.get("session_prev_lon"))
            if features.get("session_prev_lon") is not None
            else None
        )
        pts = (
            float(features.get("session_prev_ts"))
            if features.get("session_prev_ts") is not None
            else None
        )
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
    await _maybe_await(r.raise_for_status())
    data = await _maybe_await(r.json())
    return data if isinstance(data, dict) else None


async def _fetch_location_evaluation_wrapped(
    http: httpx.AsyncClient,
    body: EvaluateRequest,
    features: dict[str, Any],
    degrade_tags: list[str],
) -> dict[str, Any] | None:
    from decision_api.evaluate.score import tag_hop_unconfigured

    if tag_hop_unconfigured(degrade_tags, "location"):
        return None
    try:
        return await _circuit_location.call(
            lambda: _fetch_location_evaluation(http, body, features)
        )
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
    profile = str(
        features.get("calibration_profile")
        or body.payload.get("calibration_profile")
        or "default"
    )
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
    await _maybe_await(r.raise_for_status())
    data = await _maybe_await(r.json())
    return data if isinstance(data, dict) else None


async def _fetch_calibration_adjustment_wrapped(
    http: httpx.AsyncClient,
    body: EvaluateRequest,
    baseline_confidence: float,
    features: dict[str, Any],
    degrade_tags: list[str],
) -> dict[str, Any] | None:
    from decision_api.evaluate.score import tag_hop_unconfigured

    if tag_hop_unconfigured(degrade_tags, "calibration"):
        return None
    try:
        return await _circuit_calibration.call(
            lambda: _fetch_calibration_adjustment(
                http, body, baseline_confidence, features
            )
        )
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
    from decision_api.evaluate.score import tag_hop_unconfigured

    if tag_hop_unconfigured(degrade_tags, "ml"):
        return None, {}
    try:
        score, extra = await _circuit_ml.call(
            lambda: _fetch_ml_score(http, tenant_id, entity_id, event_type, features)
        )
    except CircuitOpenError:
        _circuit_metrics_inc("tarka_circuit_open_total_ml")
        degrade_tags.append("ml:unavailable")
        return None, {}
    reason = extra.get("unscored_reason") if isinstance(extra, dict) else None
    if score is None and reason == "disabled":
        if "ml:disabled" not in degrade_tags:
            degrade_tags.append("ml:disabled")
    elif score is None:
        if "ml:unavailable" not in degrade_tags:
            degrade_tags.append("ml:unavailable")
    return score, extra if isinstance(extra, dict) else {}


async def _evaluate_opa_wrapped(
    http: httpx.AsyncClient,
    snapshot: dict[str, Any],
    degrade_tags: list[str],
    tenant_flags: dict[str, Any],
) -> dict[str, Any] | None:
    if tenant_flag_enabled(tenant_flags, "disable_opa"):
        degrade_tags.append("opa:disabled_by_tenant")
        return None
    if apply_opa_unconfigured(degrade_tags, settings.opa_url):
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


def _normalize_explainability_tier(raw: str | None) -> str:
    tier = str(raw or "").strip().lower()
    if tier in {"minimal", "analyst", "full"}:
        return tier
    return "minimal"


def _shape_inference_context_for_tier(
    inference_context: dict[str, Any], tier: str
) -> dict[str, Any]:
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
        out["top_signals"] = list(
            dict.fromkeys(
                str(s).split(":", 1)[0] for s in top_signals if str(s).strip()
            )
        )

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
    can_view_analyst = bool(
        user and hasattr(user, "has_role") and user.has_role("analyst")
    )

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
    policy_set_id: str | None = None,
) -> dict[str, Any]:
    rule_pack_joined = ",".join(
        sorted(str(x).strip() for x in json_rule_pack_files if str(x).strip())
    )
    if policy_set_id is None:
        try:
            from decision_api.policy_set import current_policy_set_id

            policy_set_id = current_policy_set_id()
        except Exception:
            policy_set_id = ""
    return {
        "decision_api_revision": (
            os.environ.get("GIT_SHA") or os.environ.get("COMMIT_SHA") or ""
        ).strip(),
        "inference_schema_version": INFERENCE_SCHEMA_VERSION,
        "rule_pack_files": sorted(
            str(x).strip() for x in json_rule_pack_files if str(x).strip()
        ),
        "rule_pack_fingerprint_sha256": hashlib.sha256(
            rule_pack_joined.encode("utf-8")
        ).hexdigest()
        if rule_pack_joined
        else "",
        "policy_set_id": policy_set_id or "",
        "score_blend_strategy": settings.score_blend_strategy,
        "counter_version": _audit_counter_version_label(),
        "ml_model": str(inf_ctx.get("ml_model") or ""),
        "graph_checkpoint": graph_checkpoint or "",
        "policy_experiment_id": str(inf_ctx.get("policy_experiment_id") or ""),
        "challenge_policy_id": challenge_policy_id or "",
        "consortium_hash_scope": settings.consortium_hash_scope,
        "external_signal_providers": list(
            (external_signal_meta or {}).get("providers") or []
        ),
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
        _valid_api_keys = (
            frozenset(k.strip() for k in raw.split(",") if k.strip())
            if raw
            else frozenset()
        )
    return _valid_api_keys


async def require_api_key(request: Request) -> None:
    keys = _get_api_keys()
    if not keys:
        allow = os.environ.get("ALLOW_INSECURE_NO_AUTH", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
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
    log.info("decision-api canonical package (services/decision-api)")
    from decision_api.production_profile import (
        assert_production_env,
        should_enforce_production_profile,
    )

    if should_enforce_production_profile(os.environ):
        assert_production_env(os.environ)

    from tarka_core.cache import LocalDictCache, RedisCache
    from tarka_core.messaging import LocalAsyncBroker, NatsBroker, NullMessageBroker

    application.state.message_broker = NullMessageBroker()
    application.state.kv_cache = None

    await init_db()
    await open_analytics_infra(application)

    if settings.use_local_message_broker:
        application.state.kv_cache = LocalDictCache()
        await redis_tags.connect(kv_fallback=application.state.kv_cache)
        mb = LocalAsyncBroker()
        await mb.start()
        application.state.message_broker = mb
    else:
        if (settings.redis_url or "").strip():
            rc = RedisCache(settings.redis_url)
            await rc.connect()
            application.state.kv_cache = rc
        else:
            application.state.kv_cache = LocalDictCache()
        if (settings.redis_url or "").strip():
            await redis_tags.connect()
        else:
            await redis_tags.connect(kv_fallback=application.state.kv_cache)
        if (settings.nats_url or "").strip():
            try:
                import nats

                nc = await nats.connect(settings.nats_url)
                application.state.message_broker = NatsBroker(nc, nc.jetstream())
                log.info("Connected to NATS at %s", settings.nats_url)
            except Exception as e:
                log.warning("NATS connection failed (publishing disabled): %s", e)
                application.state.message_broker = NullMessageBroker()
        else:
            application.state.message_broker = NullMessageBroker()

    await maybe_hydrate_sandbox_plg_pack(application)
    load_rules()
    load_typology_definitions()
    _touch_rules_materialized()
    load_challenge_policies(force=True)
    load_shadow_rules()
    if redis_tags._client:
        agg_store.set_client(redis_tags._client)
        fingerprint_store.set_client(redis_tags._client)
        entity_link_store.set_client(redis_tags._client)
        from decision_api.ehailing_escalation import ehailing_challenge_store
        from decision_api.marketplace_kyb_store import kyb_store

        kyb_store.set_client(redis_tags._client)
        ehailing_challenge_store.set_client(redis_tags._client)
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

    from decision_api.vendors.bootstrap import install_vendor_plugins_from_settings

    install_vendor_plugins_from_settings()

    application.state.eval_load_guard = EvalLoadGuard(
        settings.tarka_max_concurrent_evaluations
    )

    retention_task = None
    if DEFAULT_RETENTION_DAYS > 0:
        retention_task = asyncio.create_task(retention_loop())

    yield

    if hasattr(application.state, "list_store") and application.state.list_store:
        await application.state.list_store.close()
    if retention_task:
        retention_task.cancel()
    broker = getattr(application.state, "message_broker", None)
    if broker is not None:
        await broker.aclose()
    kv = getattr(application.state, "kv_cache", None)
    if kv is not None:
        await kv.aclose()
    await application.state.http.aclose()
    await close_analytics_infra(application)
    await redis_tags.close()


app = FastAPI(
    title="Tarka Decision API",
    version="4.0.0",
    lifespan=lifespan,
)
if os.environ.get("TARKA_CORE_API_SUBAPP", "").strip() != "1":
    setup_observability(app, "decision-api")
    setup_tracing(app, "decision-api")
setup_security_headers(app)
setup_auth(app)
setup_rate_limiter(app, rpm=int(os.environ.get("RATE_LIMIT_RPM", "1000")))

if settings.request_signature_secret:
    from decision_api.request_signature_middleware import (
        SIGNED_PATH_PREFIXES,
        RequestSignatureMiddleware,
    )

    app.add_middleware(
        RequestSignatureMiddleware,
        secret=settings.request_signature_secret,
        path_prefixes=SIGNED_PATH_PREFIXES,
        max_skew_seconds=settings.request_signature_max_skew_seconds,
    )

from decision_api.analytics_dashboards import router as analytics_dashboards_router  # noqa: E402
from decision_api.backtest_api import router as backtest_router  # noqa: E402
from decision_api.ml_export_api import router as ml_export_router  # noqa: E402
from decision_api.calibration_api import router as calibration_router  # noqa: E402
from decision_api.event_qa import router as event_qa_router  # noqa: E402
from decision_api.captcha import router as captcha_router  # noqa: E402
from decision_api.compliance_api import router as compliance_router  # noqa: E402
from decision_api.consortium_api import router as consortium_router  # noqa: E402
from decision_api.feature_store_api import router as feature_store_router  # noqa: E402
from decision_api.experiment_api import (  # noqa: E402
    experiment_registry_line_count,
    router as experiment_router,
)
from decision_api.benchmark_export_api import router as benchmark_export_router  # noqa: E402
from decision_api.drift_query_api import router as drift_query_router  # noqa: E402
from decision_api.health_deep import run_deep_health, run_unified_health  # noqa: E402
from decision_api.internal_counters_api import router as internal_counters_router  # noqa: E402
from decision_api.manifest_compare_api import router as manifest_compare_router  # noqa: E402
from decision_api.manifest_visualize_api import router as manifest_visualize_router  # noqa: E402
from decision_api.micro_dev_onboarding import router as micro_dev_onboarding_router  # noqa: E402
from decision_api.recommend_api import router as recommend_router  # noqa: E402
from decision_api.replay import router as replay_router  # noqa: E402
from decision_api.reporting_nl import router as reporting_nl_router  # noqa: E402
from decision_api.rule_api import router as rule_router  # noqa: E402
from decision_api.ast_rule_api import router as ast_rules_router  # noqa: E402
from decision_api.rule_compiler_api import (  # noqa: E402
    rego_deprecation_router,
    router as rule_compiler_router,
)
from decision_api.rule_gitops_api import router as rule_gitops_router  # noqa: E402
from decision_api.simulation_api import router as simulation_router  # noqa: E402
from decision_api.vendor_marketplace_api import router as vendor_marketplace_router  # noqa: E402
from decision_api.marketplace_kyb_api import router as marketplace_kyb_router  # noqa: E402
from decision_api.chargeback_alert_api import router as chargeback_alert_router  # noqa: E402
from decision_api.late_label_api import router as late_label_router  # noqa: E402
from decision_api.trend_agent_api import router as trend_agent_router  # noqa: E402
from decision_api.sandbox_bootstrap import (  # noqa: E402
    maybe_hydrate_sandbox_plg_pack,
    router as sandbox_bootstrap_router,
)

app.include_router(rule_router)
app.include_router(ast_rules_router)
app.include_router(replay_router)
app.include_router(simulation_router)
app.include_router(benchmark_export_router)
app.include_router(drift_query_router)
app.include_router(experiment_router)
app.include_router(recommend_router)
app.include_router(compliance_router)
app.include_router(captcha_router)
app.include_router(lists_router)
app.include_router(consortium_router)
app.include_router(internal_counters_router)
app.include_router(calibration_router)
app.include_router(event_qa_router)
app.include_router(reporting_nl_router)
app.include_router(rego_deprecation_router)
app.include_router(rule_compiler_router)
app.include_router(rule_gitops_router)
app.include_router(backtest_router)
app.include_router(ml_export_router)
app.include_router(feature_store_router)
app.include_router(analytics_dashboards_router)
app.include_router(manifest_visualize_router)
app.include_router(manifest_compare_router)
app.include_router(vendor_marketplace_router)
app.include_router(marketplace_kyb_router)
app.include_router(chargeback_alert_router)
app.include_router(late_label_router)
app.include_router(trend_agent_router)
app.include_router(sandbox_bootstrap_router)
app.include_router(micro_dev_onboarding_router)


def _http(request: Request) -> httpx.AsyncClient:
    return request.app.state.http


def _external_nats_connected(broker: Any) -> bool | None:
    from tarka_core.messaging import NatsBroker

    if not isinstance(broker, NatsBroker):
        return None
    return broker.has_active_connection


# ---------- health ----------


@app.get("/v1/health")
async def health():
    return {"status": "ok"}


@app.get("/v1/ready")
async def ready():
    """Liveness for compose healthchecks (`/decisions/v1/ready`)."""
    return {"status": "ok"}


@app.get("/health")
async def health_unified(request: Request):
    """Unified readiness: Postgres, Redis ping, ClickHouse read/write, Rust rule engine + manifest ingest."""
    return await run_unified_health(request)


@app.get("/v1/health/deep")
async def health_deep(request: Request):
    """Deep readiness: Redis ping latency, ClickHouse probes, Rust ingest gate (503 when unhealthy)."""
    return await run_deep_health(request)


@app.get("/health/deep")
async def health_deep_alias(request: Request):
    """Alias for operators expecting `/health/deep` (same payload as `/v1/health/deep`)."""
    return await run_deep_health(request)


@app.get("/v1/slo")
async def slo_status():
    """In-process SLO snapshot (v1.2.5 R1) — targets are aspirational; ``current`` from local HTTP metrics."""
    m = get_metrics()
    cur = m.request_count_summary()
    degraded_raw = m.custom_counters_matching("tarka_degraded_decision_")
    by_reason: dict[str, int] = {}
    for name, val in degraded_raw.items():
        if name == "tarka_degraded_decision_total":
            continue
        # tarka_degraded_decision_<reason>_total → reason
        reason = name.removeprefix("tarka_degraded_decision_").removesuffix("_total")
        if reason:
            by_reason[reason] = int(val)
    return {
        "service": "decision-api",
        "availability_target_pct": 99.9,
        "latency_target_ms_p95": 50,
        "error_budget_window_days": 30,
        "targets_note": "Latency/availability measured vs your SLO stack (Prometheus/Grafana); this endpoint exposes in-process counters only.",
        "current": {
            **cur,
            "redis_connected": redis_tags.is_tag_store_available,
            "nats_connected": _external_nats_connected(
                getattr(app.state, "message_broker", None)
            ),
            "evaluate_require_idempotency_key": settings.evaluate_require_idempotency_key,
        },
        "degraded_decisions": {
            "total": int(degraded_raw.get("tarka_degraded_decision_total", 0)),
            "by_reason": by_reason,
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
        has_ml_plane = bool(
            (settings.feature_service_url or "").strip()
            or (settings.ml_scoring_url or "").strip()
        )
        if not has_graph and not has_nats and not has_ml_plane:
            deployment_tier = "community"
        else:
            deployment_tier = "pro"

    data = load_typology_definitions()
    typologies = (
        data.get("typologies") if isinstance(data.get("typologies"), list) else []
    )
    typology_count = len(
        [
            t
            for t in typologies
            if isinstance(t, dict) and str(t.get("id") or "").strip()
        ]
    )

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
            "ok": redis_tags.is_tag_store_available,
            "detail": "connected"
            if redis_tags.is_tag_store_available
            else "not_connected",
        },
        {
            "id": "graph_service_configured",
            "ok": bool((settings.graph_service_url or "").strip()),
            "detail": "set" if (settings.graph_service_url or "").strip() else "empty",
        },
        {
            "id": "feature_service_configured",
            "ok": bool((settings.feature_service_url or "").strip()),
            "detail": "set"
            if (settings.feature_service_url or "").strip()
            else "empty",
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
        last_reload_iso = (
            datetime.fromtimestamp(last_reload, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

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
        "auth_path": {
            "p99_budget_ms": settings.auth_path_p99_budget_ms,
            "loyalty_bridge_timeout_seconds": settings.loyalty_abuse_timeout_seconds,
            "loyalty_bridge_circuit_failure_threshold": (
                settings.loyalty_abuse_circuit_failure_threshold
            ),
            "excludes": ["shadow_llm", "graph_upsert", "investigation_agent"],
            "doc": "docs/docs/guides/auth-vs-forensics-path.md",
        },
        "request_id": request.headers.get("x-request-id")
        or request.headers.get("x-correlation-id"),
    }


@app.get("/v1/ops/partner-fusion-status")
async def partner_fusion_status_ops(_user=Depends(require_role("analyst"))):
    """L2 LIVE|WAIVED honesty surface (P0-L2). Never forge LIVE pins."""
    from decision_api.partner_fusion_status import load_partner_fusion_status

    return load_partner_fusion_status()


@app.get("/v1/ops/loyalty-feed-posture")
async def loyalty_feed_posture_ops(_user=Depends(require_role("analyst"))):
    """C1 loyalty feed-gate honesty — incomplete feeds never allow live claims."""
    from decision_api.loyalty_feed_posture import load_loyalty_feed_ops_posture

    return load_loyalty_feed_ops_posture(
        loyalty_abuse_url=settings.loyalty_abuse_url,
        loyalty_abuse_api_key=settings.loyalty_abuse_api_key,
    )


@app.get("/v1/ops/feature-store-posture")
async def feature_store_posture_ops(_user=Depends(require_role("analyst"))):
    """Online/offline feature-store ops posture — Redis ≠ Feast/Flink claims."""
    from decision_api.feature_store_posture import load_feature_store_ops_posture

    return load_feature_store_ops_posture(
        rules_path=settings.rules_path,
        redis_url=settings.redis_url,
    )


@app.get("/v1/ops/diligence-readiness")
async def diligence_readiness_ops(_user=Depends(require_role("analyst"))):
    """Aggregate honesty gates for customer diligence (not SOC2 attestation)."""
    from decision_api.diligence_readiness import load_diligence_readiness

    return load_diligence_readiness(
        rules_path=settings.rules_path,
        redis_url=settings.redis_url,
        loyalty_abuse_url=settings.loyalty_abuse_url,
        loyalty_abuse_api_key=settings.loyalty_abuse_api_key,
    )


@app.get("/v1/ops/l3-ledger")
async def l3_ops_ledger_get(_user=Depends(require_role("analyst"))):
    """Four-week live shadow ledger. Sim cannot advance this file."""
    from decision_api.host_action_log import count_actions, sink_uri
    from decision_api.l3_ops_ledger import public_view

    view = public_view()
    tid = view.get("tenant_id")
    view["host_action_log_count"] = count_actions(str(tid) if tid else None)
    view["internal_host_action_sink"] = sink_uri()
    return view


class L3ArmBody(BaseModel):
    tenant_id: str = Field(..., min_length=2, max_length=128)
    week1_start_utc: str = Field(..., min_length=8, max_length=32)
    host_action_sink: str = Field(
        ...,
        min_length=3,
        max_length=512,
        description="URL or internal:jsonl:… sink; use GET /v1/ops/l3-ledger.internal_host_action_sink",
    )
    shadow_evaluate_enabled: bool = True
    label_join_ece: bool = False
    actor: str = Field(default="operator", max_length=128)


@app.post("/v1/ops/l3-ledger/arm")
async def l3_ops_ledger_arm(
    body: L3ArmBody,
    _user=Depends(require_role("admin")),
):
    """Arm L3 clock on a named live tenant. Arming ≠ COMPLETE claim."""
    from decision_api.l3_ops_ledger import arm_ledger, public_view

    result = arm_ledger(
        tenant_id=body.tenant_id,
        week1_start_utc=body.week1_start_utc,
        host_action_sink=body.host_action_sink,
        shadow_evaluate_enabled=body.shadow_evaluate_enabled,
        actor=body.actor,
        label_join_ece=body.label_join_ece,
    )
    if not result.get("ok"):
        raise HTTPException(
            status_code=409,
            detail={
                "blockers": result.get("blockers"),
                "ledger": public_view(result.get("ledger")),
            },
        )
    return {"ok": True, "ledger": public_view(result.get("ledger"))}


class L3SignWeekBody(BaseModel):
    shadow_on: bool = False
    host_actions_logged: bool = False
    outcomes_joined: bool = False
    weekly_metrics: bool = False
    ece_candidate: bool = False
    sign_off: bool = False
    actor: str = Field(default="operator", max_length=128)


@app.post("/v1/ops/l3-ledger/weeks/{week}/sign")
async def l3_ops_ledger_sign_week(
    week: int,
    body: L3SignWeekBody,
    _user=Depends(require_role("admin")),
):
    """Sign a live week checklist. Week 4 requires ECE on real labels."""
    from decision_api.l3_ops_ledger import public_view, sign_week

    result = sign_week(
        week=week,
        checklist={
            "shadow_on": body.shadow_on,
            "host_actions_logged": body.host_actions_logged,
            "outcomes_joined": body.outcomes_joined,
            "weekly_metrics": body.weekly_metrics,
            "ece_candidate": body.ece_candidate,
            "sign_off": body.sign_off,
        },
        actor=body.actor,
    )
    if not result.get("ok"):
        raise HTTPException(
            status_code=409,
            detail={
                "blockers": result.get("blockers"),
                "ledger": public_view(result.get("ledger")),
            },
        )
    return {"ok": True, "ledger": public_view(result.get("ledger"))}


class HostActionBody(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=128)
    action: str = Field(..., min_length=1, max_length=128)
    entity_id: str | None = Field(default=None, max_length=256)
    trace_id: str | None = Field(default=None, max_length=128)
    actor: str = Field(default="operator", max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)


@app.post("/v1/ops/host-actions")
async def post_host_action(
    body: HostActionBody,
    _user=Depends(require_role("analyst")),
):
    """Append host action for L3 sink (internal JSONL)."""
    from decision_api.host_action_log import append_host_action, sink_uri

    try:
        rec = append_host_action(
            tenant_id=body.tenant_id,
            action=body.action,
            entity_id=body.entity_id,
            trace_id=body.trace_id,
            actor=body.actor,
            metadata=body.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "record": rec, "sink": sink_uri()}


@app.get("/v1/admin/typology/telemetry")
async def typology_weighted_telemetry(_user=Depends(require_role("analyst"))):
    """Configured typology weights + aggregation mode (P1-typ)."""
    return weighted_aggregation_telemetry()


@app.get("/v1/ops/typology-ops")
async def typology_ops_posture(
    sample_rule_hits: str = "",
    tenant_id: str = "",
    vertical: str = "",
    session: AsyncSession = Depends(get_session),
    _user=Depends(require_role("analyst")),
):
    """Tazama-class typology control plane (weights + breach; not ISO 20022)."""
    from decision_api.typology_ops import (
        aggregate_typology_breaches_from_audits,
        load_typology_ops_posture,
    )

    hits = [h.strip() for h in (sample_rule_hits or "").split(",") if h.strip()]
    hist = None
    tid = (tenant_id or "").strip()
    if tid:
        try:
            result = await session.execute(
                select(AuditRecord)
                .where(AuditRecord.tenant_id == tid)
                .order_by(AuditRecord.created_at.desc())
                .limit(500)
            )
            records = result.scalars().all()
            hist = aggregate_typology_breaches_from_audits(
                [
                    {
                        "payload_snapshot": rec.payload_snapshot
                        if isinstance(rec.payload_snapshot, dict)
                        else {},
                    }
                    for rec in records
                ]
            )
        except Exception:
            hist = {
                "schema_id": "tarka.typology_breach_histogram/v1",
                "audits_scanned": 0,
                "rows_with_typology_summary": 0,
                "highest_breach_counts": {},
                "driver_typology_counts": {},
                "alert_or_warning_rows": 0,
                "note": "audit scan failed",
            }
    return load_typology_ops_posture(
        sample_rule_hits=hits or None,
        audit_breach_histogram=hist,
        vertical=(vertical or "").strip() or None,
    )


@app.get("/v1/ops/connector-posture")
async def connector_ops_posture(_user=Depends(require_role("analyst"))):
    """Production connector contract posture (device/KYB/chargeback/…)."""
    from decision_api.connector_contract import load_all_connector_posture

    return load_all_connector_posture()


@app.get("/v1/ops/vertical-pack-posture")
async def vertical_pack_ops_posture(_user=Depends(require_role("analyst"))):
    """Vertical packs + required connector readiness (marketplace-first)."""
    from decision_api.connector_contract import load_all_connector_posture
    from decision_api.vertical_packs import load_vertical_pack_ops_posture

    connectors = load_all_connector_posture()
    return load_vertical_pack_ops_posture(
        connector_families=connectors.get("families") or {}
    )


@app.get("/v1/ops/depth-engines")
async def depth_engines_ops_posture(_user=Depends(require_role("analyst"))):
    """OSS depth engines — schemas, methods, host inputs (no forged LIVE)."""
    from decision_api.depth_engines_ops import load_depth_engines_ops_posture

    return load_depth_engines_ops_posture()


@app.get("/v1/ops/vertical-promote-posture")
async def vertical_promote_ops_posture(_user=Depends(require_role("analyst"))):
    """Per-pack fixture holdout promote science (F1 + McNemar; no LIVE labels)."""
    from decision_api.vertical_promote_registry import load_all_vertical_promote_posture

    return load_all_vertical_promote_posture()


@app.get("/v1/ops/vertical-calibration")
async def vertical_calibration_ops(_user=Depends(require_role("analyst"))):
    """Per-vertical reliability bins from fixture holdouts (not LIVE calibration)."""
    from decision_api.vertical_calibration import load_all_vertical_calibration_posture

    return load_all_vertical_calibration_posture()


@app.get("/v1/ops/sibling-bridge-posture")
async def sibling_bridge_ops_posture(_user=Depends(require_role("analyst"))):
    """Loyalty / refund / cancel sibling bridge config + circuit honesty."""
    from decision_api.sibling_bridge_posture import load_sibling_bridge_ops_posture

    return load_sibling_bridge_ops_posture(
        loyalty_abuse_url=settings.loyalty_abuse_url,
        loyalty_abuse_api_key=settings.loyalty_abuse_api_key,
    )


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
            return {
                "valid": False,
                "device_integrity": None,
                "reason": "invalid_token_format",
            }
        log.warning(
            "Play Integrity token received but server-side verification not configured. Set PLAY_INTEGRITY_CREDENTIALS to enable full verification."
        )
        return {
            "valid": True,
            "device_integrity": "play_integrity_unverified",
            "warning": "Server-side verification pending configuration",
        }

    if body.provider == "app_attest":
        # Apple App Attest: token is a CBOR-encoded attestation object.
        # Requires server-side verification with Apple's attestation service.
        if not body.token or len(body.token) < 50:
            return {
                "valid": False,
                "device_integrity": None,
                "reason": "invalid_token_format",
            }
        log.warning(
            "App Attest token received but server-side verification not configured. Set APP_ATTEST_TEAM_ID to enable full verification."
        )
        return {
            "valid": True,
            "device_integrity": "app_attest_unverified",
            "warning": "Server-side verification pending configuration",
        }

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


def _integrity_ingress_ops_block() -> dict[str, Any]:
    from decision_api.challenge_orchestrator import challenge_webhook_configured
    from decision_api.enforcement import enforcement_webhook_configured
    from decision_api.integrity_policy import integrity_ingress_status
    from decision_api.request_signature_middleware import SIGNED_PATH_PREFIXES

    replay_ttl = int(os.environ.get("REPLAY_PAYLOAD_TTL_SECONDS", "300"))
    return integrity_ingress_status(
        request_signature_required=bool(settings.request_signature_secret),
        request_signature_max_skew_seconds=int(
            settings.request_signature_max_skew_seconds
        ),
        integrity_soft_tags=bool(settings.integrity_soft_tags),
        challenge_webhook_configured=challenge_webhook_configured(),
        enforcement_webhook_configured=enforcement_webhook_configured(),
        replay_payload_ttl_seconds=replay_ttl,
        request_signature_path_prefixes=SIGNED_PATH_PREFIXES,
    )


@app.get("/v1/ops/enforcement-journal")
async def ops_enforcement_journal(limit: int = 50):
    """Tail of append-only enforcement delivery journal (ack / non_2xx / error / skipped)."""
    from decision_api.enforcement import (
        enforcement_journal_line_count,
        enforcement_journal_path,
        read_enforcement_journal,
    )

    return {
        "schema_id": "tarka.enforcement_delivery_list/v1",
        "path": str(enforcement_journal_path()),
        "line_count": enforcement_journal_line_count(),
        "items": read_enforcement_journal(limit),
    }


@app.get("/v1/ops/governance")
async def ops_governance():
    """Rollout posture: active rule packs (canary, effective_at), shadow count, inference contract version."""
    from decision_api.enforcement import enforcement_journal_line_count

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
            await _maybe_await(r.raise_for_status())
            data = await _maybe_await(r.json())
            cal_status = (
                data
                if isinstance(data, dict)
                else {"hint": "invalid_calibration_response"}
            )
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
        "enforcement_journal_lines": enforcement_journal_line_count(),
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
            "doc": "docs/docs/guides/device-id-semantics.md",
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
        "integrity_ingress": _integrity_ingress_ops_block(),
    }


@app.get("/v1/ops/calibration-status")
async def calibration_status(
    tenant_id: str,
    profile: str = "default",
    session: AsyncSession = Depends(get_session),
):
    """Small ops view that combines drift hint with label-coverage posture."""
    from decision_api.label_join import label_coverage_posture
    from decision_api.reliability_export import (
        audit_row_to_export_dict,
        reliability_bins,
    )

    if settings.calibration_service_url:
        try:
            r = await app.state.http.get(
                settings.calibration_service_url.rstrip("/") + "/v1/drift",
                params={"tenant_id": tenant_id, "profile_id": profile},
                timeout=settings.eval_step_feature_snapshot_timeout_seconds,
            )
            await _maybe_await(r.raise_for_status())
            data = await _maybe_await(r.json())
            drift = (
                data
                if isinstance(data, dict)
                else {"hint": "invalid_calibration_response"}
            )
        except Exception:
            drift = {"hint": "calibration_service_unavailable"}
    else:
        drift = {"hint": "calibration_service_not_configured"}

    # Label coverage from recent audits (proxy-only ⇒ not healthy).
    label_posture: dict[str, Any] = {
        "healthy": False,
        "status": "no_audit_rows",
        "label_coverage": 0.0,
        "hint": "no_audit_rows",
    }
    try:
        stmt = (
            select(AuditRecord)
            .where(AuditRecord.tenant_id == tenant_id)
            .order_by(AuditRecord.created_at.desc())
            .limit(500)
        )
        result = await session.execute(stmt)
        records = result.scalars().all()
        export_rows = [
            audit_row_to_export_dict(
                {
                    "trace_id": rec.trace_id,
                    "tenant_id": rec.tenant_id,
                    "entity_id": rec.entity_id,
                    "event_type": rec.event_type,
                    "decision": rec.decision,
                    "score": rec.score,
                    "payload_snapshot": rec.payload_snapshot,
                    "created_at": rec.created_at,
                }
            )
            for rec in records
        ]
        bins = reliability_bins(export_rows, n_bins=10, use_proxy_labels=True)
        label_posture = label_coverage_posture(
            label_coverage=float(bins.get("label_coverage") or 0.0),
            proxy_only=bins.get("label_source") == "proxy_from_decision",
        )
        label_posture["label_source"] = bins.get("label_source")
        label_posture["rows_scanned"] = len(export_rows)
    except Exception:
        label_posture = {
            "healthy": False,
            "status": "label_coverage_unavailable",
            "label_coverage": 0.0,
            "hint": "label_coverage_unavailable",
        }

    healthy = bool(label_posture.get("healthy")) and drift.get("hint") not in {
        "calibration_service_unavailable",
        "elevated_drift_recalibrate",
    }
    return {
        "tenant_id": tenant_id,
        "profile": profile,
        "inference_schema_version": INFERENCE_SCHEMA_VERSION,
        "challenge_policy_default": settings.challenge_policy_default,
        "calibration": drift,
        "label_coverage": label_posture,
        "healthy": healthy,
    }


@app.get("/v1/ops/integrity-policy")
async def integrity_policy_ops():
    """Wave 2: publish platform × attestation matrix for ops and CI."""
    from decision_api.integrity_policy import integrity_policy_matrix

    return integrity_policy_matrix()


@app.get("/v1/challenge-policies")
async def list_challenge_policy_templates():
    """List loaded challenge / escalation policy templates (JSON under rules/challenge_policies/)."""
    from decision_api.challenge_policy import get_policy_summaries

    return {"policies": get_policy_summaries()}


@app.get("/v1/policy/posture")
async def policy_posture():
    """Versioned policy-set posture: JSON packs + typology + challenge policies + integrity."""
    from decision_api.integrity_policy import integrity_policy_matrix
    from decision_api.policy_set import get_policy_set_manifest

    manifest = get_policy_set_manifest()
    # Integrity is ops context — not part of policy_set_id hash.
    manifest["integrity"] = {
        "ingress": _integrity_ingress_ops_block(),
        "matrix": integrity_policy_matrix(),
    }
    return manifest


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
    data_residency_region: Literal["EU", "US", "GLOBAL"] | None = None


@app.get("/v1/admin/tenants/{tenant_id}/flags")
async def get_tenant_flags_admin(tenant_id: str, _=Depends(require_role("admin"))):
    if not redis_tags.is_tag_store_available:
        raise HTTPException(503, detail="Tag/flags store not configured")
    flags = await redis_tags.get_tenant_flags(tenant_id)
    return {"tenant_id": tenant_id, "flags": flags}


@app.patch("/v1/admin/tenants/{tenant_id}/flags")
async def patch_tenant_flags_admin(
    tenant_id: str, body: TenantFlagsBody, _=Depends(require_role("admin"))
):
    if not redis_tags.is_tag_store_available:
        raise HTTPException(503, detail="Tag/flags store not configured")
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
    "is_rooted": "sdk:rooted",
    "is_jailbroken": "sdk:jailbroken",
    "has_biometrics": "sdk:biometrics",
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


def _infer_ctx_kwargs(
    body: EvaluateRequest, features: dict[str, Any]
) -> dict[str, Any]:
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


async def _maybe_await(value: Any) -> Any:
    """Await coroutine/future results (e.g. unittest.mock.AsyncMock) from httpx-like responses."""
    if asyncio.iscoroutine(value) or asyncio.isfuture(value):
        return await value
    return value


# ---------- downstream helpers ----------


def _feature_snapshot_fallback(
    body: EvaluateRequest, redis_tag_list: list[str]
) -> dict[str, Any]:
    from decision_api.evaluate.enrichment import feature_snapshot_fallback

    return feature_snapshot_fallback(body, redis_tag_list)


async def _fetch_feature_snapshot(
    http: httpx.AsyncClient, body: EvaluateRequest, redis_tag_list: list[str]
) -> dict[str, Any]:
    from decision_api.evaluate.enrichment import fetch_feature_snapshot

    return await fetch_feature_snapshot(http, body, redis_tag_list)


async def _fetch_ml_score(
    http: httpx.AsyncClient,
    tenant_id: str,
    entity_id: str,
    event_type: str,
    features: dict[str, Any],
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
    await _maybe_await(r.raise_for_status())
    data = await _maybe_await(r.json())
    from decision_api.evaluate.score import parse_ml_score_payload

    return parse_ml_score_payload(data if isinstance(data, dict) else None)


async def _graph_upsert(
    http: httpx.AsyncClient,
    body: EvaluateRequest,
    trace_id: str,
    merged_tags: list[str],
    geo_extra_tags: list[str] | None = None,
    decision: str | None = None,
    partner_graph_hints: dict[str, Any] | None = None,
) -> None:
    if not settings.graph_service_url:
        return
    base = settings.graph_service_url.rstrip("/")
    from tarka_shared.decision_graph_payload import (
        attach_decision_object,
        build_evaluate_objects,
        normalize_markings,
        resolve_decision_source,
    )

    payload = body.payload if isinstance(body.payload, dict) else {}
    dc_dump = body.device_context.model_dump() if body.device_context else None
    objects, links = build_evaluate_objects(
        trace_id=trace_id,
        entity_id=body.entity_id,
        event_type=body.event_type.value,
        payload=payload,
        device_context=dc_dump,
        session_id=body.session_id,
    )
    if str(decision or "").strip():
        meta = body.metadata if isinstance(body.metadata, dict) else {}
        attach_decision_object(
            objects,
            links,
            person_id=body.entity_id,
            trace_id=trace_id,
            outcome=str(decision),
            kind="evaluate",
            source=resolve_decision_source(meta),
            markings=normalize_markings(meta.get("markings")),
        )
    device_tags = extract_signal_tags(dc_dump) if dc_dump else []
    for obj in objects:
        oid = str(obj.get("external_id") or "").strip()
        etype = str(obj.get("entity_type") or "Custom").strip() or "Custom"
        if not oid:
            continue
        props = (
            dict(obj.get("properties") or {})
            if isinstance(obj.get("properties"), dict)
            else {}
        )
        tags: list[str] = []
        if etype == "Person":
            tags = merged_tags
            props["last_event"] = body.event_type.value
        elif etype == "Device" and body.device_context:
            tags = device_tags
            props["platform"] = body.device_context.platform
            props.update(
                {
                    k: v
                    for k, v in body.device_context.signals.items()
                    if isinstance(v, (str, bool, int, float)) or v is None
                }
            )
        await http.post(
            f"{base}/v1/entities",
            json={
                "tenant_id": body.tenant_id,
                "entity_type": etype,
                "external_id": oid,
                "properties": props,
                "tags": tags,
            },
            headers=_upstream_headers(),
        )
    for link in links:
        src = str(link.get("from_external_id") or "").strip()
        dst = str(link.get("to_external_id") or "").strip()
        rel = str(link.get("relationship") or "").strip()
        if not src or not dst or not rel:
            continue
        await http.post(
            f"{base}/v1/links",
            json={
                "tenant_id": body.tenant_id,
                "from_external_id": src,
                "to_external_id": dst,
                "relationship": rel,
                "properties": {
                    "trace_id": trace_id,
                    "event_type": body.event_type.value,
                },
            },
            headers=_upstream_headers(),
        )

    # Place / SEEN_AT is not in Hunt objects yet — keep it on this hop only.
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
    if (
        la_f is not None
        and lo_f is not None
        and -90 <= la_f <= 90
        and -180 <= lo_f <= 180
    ):
        from tarka_shared.decision_graph_payload import place_cell_id

        cell = place_cell_id(la_f, lo_f)
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
                "properties": {
                    "trace_id": trace_id,
                    "event_type": body.event_type.value,
                },
            },
            headers=_upstream_headers(),
        )
        sess = str(body.session_id or "").strip()
        sess_ext = f"sess:{sess}" if sess and not sess.startswith("sess:") else sess
        if sess_ext:
            await http.post(
                f"{base}/v1/links",
                json={
                    "tenant_id": body.tenant_id,
                    "from_external_id": sess_ext,
                    "to_external_id": cell,
                    "relationship": "SEEN_AT",
                    "properties": {"trace_id": trace_id},
                },
                headers=_upstream_headers(),
            )

    from decision_api.partner_fusion import graph_writes_from_hints

    hint_objs, hint_links = graph_writes_from_hints(partner_graph_hints)
    for obj in hint_objs:
        await http.post(
            f"{base}/v1/entities",
            json={
                "tenant_id": body.tenant_id,
                "entity_type": obj["entity_type"],
                "external_id": obj["external_id"],
                "properties": {
                    **obj["properties"],
                    "trace_id": obj["properties"].get("trace_id") or trace_id,
                },
            },
            headers=_upstream_headers(),
        )
    for link in hint_links:
        props = dict(link["properties"])
        props.setdefault("trace_id", trace_id)
        await http.post(
            f"{base}/v1/links",
            json={
                "tenant_id": body.tenant_id,
                "from_external_id": link["from_external_id"],
                "to_external_id": link["to_external_id"],
                "relationship": link["relationship"],
                "properties": props,
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
    decision: str | None = None,
    partner_graph_hints: dict[str, Any] | None = None,
) -> None:
    """Background graph writes with overall timeout (#32)."""
    if tenant_flag_enabled(tenant_flags, "disable_graph"):
        return

    async def _do():
        await _graph_upsert(
            http,
            body,
            trace_id,
            merged_tags,
            geo_extra_tags,
            decision,
            partner_graph_hints,
        )

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
    from decision_api.evaluate.enrichment import fetch_graph_risk

    return await fetch_graph_risk(http, tenant_id, entity_id, graph_checkpoint)


# ---------- decision / shadow message publishing ----------


async def _publish_decision(app_state: Any, decision_data: dict) -> None:
    from tarka_core.messaging import PublishDelivery

    broker = getattr(app_state, "message_broker", None)
    if broker is None:
        return
    tenant = decision_data.get("tenant_id", "unknown")
    etype = decision_data.get("event_type", "unknown")
    subject = f"fraud.decisions.{tenant}.{etype}"
    try:
        await broker.publish(
            subject,
            _json.dumps(decision_data, default=str).encode(),
            delivery=PublishDelivery.JETSTREAM,
        )
    except Exception as e:
        log.warning("Failed to publish decision: %s", e)


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
    from tarka_core.messaging import PublishDelivery

    broker = getattr(app_state, "message_broker", None)
    if broker is None:
        return
    subject = f"fraud.shadow.{tenant_id}"
    payload = {
        "trace_id": trace_id,
        "tenant_id": tenant_id,
        "production_decision": production_decision,
        **shadow_result,
    }
    try:
        await broker.publish(
            subject,
            _json.dumps(payload, default=str).encode(),
            delivery=PublishDelivery.JETSTREAM,
        )
    except Exception as e:
        log.warning("Failed to publish shadow result: %s", e)


# ---------- main endpoint ----------


# ---------- main endpoint ----------


@app.post("/v1/decisions/evaluate", response_model=EvaluateResponse)
async def evaluate_decision(
    body: EvaluateRequest,
    request: Request,
    bg: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    from decision_api.evaluate.pipeline import run_evaluate_decision

    return await run_evaluate_decision(body, request, bg, session)


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
        allow = os.environ.get("ALLOW_INSECURE_NO_AUTH", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
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


@app.get("/v1/audit/recent")
async def get_audit_recent(
    request: Request,
    tenant_id: str = Query(..., min_length=1, max_length=128),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    from decision_api.audit_recent import shape_audit_recent_item

    result = await session.execute(
        select(AuditRecord)
        .where(AuditRecord.tenant_id == tenant_id)
        .order_by(AuditRecord.created_at.desc())
        .limit(limit)
    )
    rows = result.scalars().all()
    return {"items": [shape_audit_recent_item(r) for r in rows]}


@app.get("/v1/audit/{trace_id}")
async def get_audit(
    trace_id: UUID,
    request: Request,
    tenant_id: str = Query(..., description="Must match the audit row tenant_id"),
    detail_level: str = Query("minimal", pattern="^(minimal|analyst|full)$"),
    session: AsyncSession = Depends(get_session),
):
    user = getattr(request.state, "auth_user", None)
    if detail_level in {"analyst", "full"} and not (
        user and hasattr(user, "has_role") and user.has_role("analyst")
    ):
        raise HTTPException(
            status_code=403, detail="analyst role required for full audit detail"
        )
    result = await session.execute(
        select(AuditRecord).where(AuditRecord.trace_id == trace_id)
    )
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
        "enforcement_action": snap.get("enforcement_action"),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
    from decision_api.device_integrity import audit_integrity

    out["integrity"] = audit_integrity(snap)
    ge = snap.get("graph_decision_explanation")
    if isinstance(ge, dict):
        out["graph_decision_explanation"] = ge
    if detail_level in {"analyst", "full"}:
        ep: dict[str, Any] = {}
        payload = snap.get("payload")
        if isinstance(payload, dict):
            ep.update(payload)
        metadata = snap.get("metadata")
        if isinstance(metadata, dict):
            ep["metadata"] = metadata
        dc = snap.get("device_context")
        if isinstance(dc, dict):
            ep["device_context"] = dc
        for k in (
            "pack_id",
            "pack_name",
            "pack_reason",
            "pack_why",
            "advise",
            "advise_status",
            "advise_error",
            "advise_timed_out",
            "reasoning",
            "rule_pack_file",
            "integrity",
        ):
            if k in snap and k not in ep:
                ep[k] = snap[k]
        out["evaluate_payload"] = ep
        reasons = snap.get("reasons")
        if isinstance(reasons, list):
            out["reasons"] = reasons
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
            "driver_reasons": [
                d
                for d in inf["driver_reasons"]
                if any(
                    x in d
                    for x in ("velocity", "travel", "device", "entity", "ml_score")
                )
            ],
        },
        "anomaly_flags": _velocity_anomaly_flags(raw_features),
    }


# Late bind after helpers exist (__import__ avoids E402 bottom-of-file import).
_enrich_mod = __import__("decision_api.evaluate.enrichment", fromlist=["bind_runtime"])
_enrich_mod.bind_runtime(
    circuit_graph=_circuit_graph,
    circuit_feature=_circuit_feature,
    metrics_inc=_metrics_inc_safe,
    upstream_headers=_upstream_headers,
)
_bind_evaluate_main = __import__(
    "decision_api.evaluate.pipeline", fromlist=["bind_main"]
).bind_main
_bind_evaluate_main(sys.modules[__name__])
