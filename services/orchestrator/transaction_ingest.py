"""Shared rule-engine + Shadow + audit persistence path for transaction envelopes."""

from __future__ import annotations

import logging
import math
import os
from datetime import UTC
from typing import Any

import httpx
from fastapi import HTTPException, Request, status
from ingestor.manifest_schema import TransactionSchema

from anumana_velocity import device_hash_token

from audit_case_worker import (
    persist_orchestrator_audit_log,
)
from database import TarkaDatabaseException, atomic_transaction
from enforcement.log_decision import persist_lekh_decision
from graph.client import GraphClient
from models.outbox import (
    OUTBOX_EVENT_GRAPH_INGEST,
    OUTBOX_EVENT_VELOCITY_UPDATE,
    OutboxDAO,
)
from queues.shadow_dispatch import dispatch_shadow_investigate_if_review
from shadow_autoresolve import (
    resolve_autoresolve_auth_token,
    try_shadow_autoresolve_after_ingest,
)
from shadow_graph_payload import build_shadow_analyze_payload
from decision_evaluate_bridge import (
    MissingTenantIdError,
    compare_rule_eval_outcomes,
    log_rule_eval_dual_run_diff,
    map_tx_to_evaluate_request,
    post_decision_evaluate,
    wire_rule_data_from_evaluate,
)
from routes.evaluate import finalize_live_evaluation_wire_payload
from shadow_hypothesis_audit import evaluate_transaction_shadow_matches
from tarka_shared.audit_errors import AuditPersistenceError

logger = logging.getLogger(__name__)

_RULE_EVAL_PYTHON = "python"
_RULE_EVAL_DECISION_API = "decision_api"


def _transaction_envelope_for_audit(transaction: TransactionSchema) -> dict[str, Any]:
    return {
        "entity_id": str(transaction.entity_id),
        "amount": float(transaction.amount),
        "timestamp": transaction.timestamp.isoformat(),
        "metadata": dict(transaction.metadata),
        "country": transaction.country,
    }


def _structural_blocking_rule_id(rule_data: dict[str, Any]) -> str | None:
    raw = rule_data.get("blocking_rule_id")
    if raw is None:
        return None
    if isinstance(raw, str):
        token = raw.strip()
        return token or None
    token = str(raw).strip()
    return token or None


def _resolved_rules_from_rule_data(rule_data: dict[str, Any]) -> dict[str, Any]:
    """Map ``evaluation_trace`` rows by ``rule_id`` for downstream graph ingest workers."""
    trace = rule_data.get("evaluation_trace")
    if not isinstance(trace, list):
        return {}
    resolved: dict[str, Any] = {}
    for row in trace:
        if not isinstance(row, dict):
            continue
        rule_id = row.get("rule_id")
        if rule_id is None:
            continue
        resolved[str(rule_id)] = dict(row)
    return resolved


def _graph_ingest_outbox_idempotency_key(transaction_id: str, audit_log_id: int) -> str:
    return f"graph_ingest:{transaction_id}:{audit_log_id}"


def _graph_ingest_outbox_payload(
    *,
    transaction: TransactionSchema,
    rule_data: dict[str, Any],
    audit_log_id: int,
) -> dict[str, Any]:
    transaction_id = str(rule_data.get("transaction_id") or transaction.entity_id)
    entity_id = str(transaction.entity_id)
    return {
        "schema": "tarka.graph_ingest.v1",
        "transaction_id": transaction_id,
        "entity_id": entity_id,
        "audit_log_id": audit_log_id,
        "resolved_rules": _resolved_rules_from_rule_data(rule_data),
        "blocking_rule_id": _structural_blocking_rule_id(rule_data),
        "edge_transaction_payload_envelope": transaction.model_dump(mode="json"),
    }


_BROWSER_METADATA_CONTEXT_KEYS: tuple[str, ...] = (
    "canvas_fingerprint",
    "canvas_raster_digest_hex",
    "ip",
    "ip_address",
    "client_claimed_ip",
    "ingress_ip",
    "tenant_id",
    "device_session_id",
    "session_id",
    "anumana_session_id",
    "telemetry_packet",
    "user_agent",
    "browser",
    "device_id",
)


def _meta_nonempty_str(meta: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        raw = meta.get(key)
        if isinstance(raw, str):
            token = raw.strip()
            if token:
                return token
    return None


def _canonical_canvas_fingerprint_from_metadata(meta: dict[str, Any]) -> str | None:
    return _meta_nonempty_str(meta, "canvas_fingerprint", "canvas_raster_digest_hex")


def _device_hash_string_from_metadata(meta: dict[str, Any]) -> str | None:
    """Stable Redis device token (``device_hash_token``) or explicit ``device_hash`` metadata."""
    explicit = _meta_nonempty_str(meta, "device_hash")
    if explicit:
        return explicit
    canvas = _canonical_canvas_fingerprint_from_metadata(meta)
    if canvas:
        return device_hash_token(canvas)
    return None


def _client_browser_metadata_context_from_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    """Browser SDK fields consumed by :mod:`orchestrator.anumana_velocity` downstream workers."""
    ctx: dict[str, Any] = {}
    for key in _BROWSER_METADATA_CONTEXT_KEYS:
        if key not in meta:
            continue
        value = meta[key]
        if value is None:
            continue
        ctx[key] = value
    return ctx


def _amount_cents_from_transaction(transaction: TransactionSchema) -> int:
    return max(0, int(round(float(transaction.amount) * 100)))


def _utc_transaction_timestamp_iso(transaction: TransactionSchema) -> str:
    ts = transaction.timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    else:
        ts = ts.astimezone(UTC)
    return ts.isoformat()


def _velocity_update_outbox_idempotency_key(transaction_id: str, audit_log_id: int) -> str:
    return f"velocity_update:{transaction_id}:{audit_log_id}"


def _velocity_update_outbox_payload(
    *,
    transaction: TransactionSchema,
) -> dict[str, Any]:
    meta = transaction.metadata if isinstance(transaction.metadata, dict) else {}
    entity_id = str(transaction.entity_id)
    return {
        "schema": "tarka.velocity_update.v1",
        "entity_id": entity_id,
        "device_hash_string": _device_hash_string_from_metadata(meta),
        "client_browser_metadata_context": _client_browser_metadata_context_from_metadata(meta),
        "amount_cents": _amount_cents_from_transaction(transaction),
        "transaction_timestamp_utc": _utc_transaction_timestamp_iso(transaction),
    }


_VELOCITY_INDICATOR_KEYS: tuple[str, ...] = (
    "velocity",
    "velocity_5m",
    "velocity_1h",
    "velocity_24h",
    "event_count_5m",
    "event_count_1h",
    "event_count_24h",
    "ip_velocity",
    "distinct_users_last_2h",
    "mouse_velocity",
    "mv",
)

_GRAPH_INDICATOR_KEYS: tuple[str, ...] = (
    "graph_score",
    "graph_linked_to_blocked_count",
    "graph_linked_to_blocked",
    "blocked_device_touch_count",
    "two_hop_distinct_cards_last_2h",
)


def _raise_audit_persistence_http(exc: AuditPersistenceError) -> None:
    raise HTTPException(
        status_code=exc.http_status,
        detail={
            "error": exc.error_code,
            "message": exc.message,
            **({"entity_id": exc.entity_id} if exc.entity_id else {}),
        },
    ) from exc


def _raise_database_transaction_http(
    exc: TarkaDatabaseException,
    *,
    entity_id: str,
) -> None:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "error": exc.error_code,
            "message": exc.message,
            "entity_id": entity_id,
        },
    ) from exc


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


def _dedupe_actions_preserve_order(actions: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for action in actions:
        if action not in seen:
            seen.add(action)
            out.append(action)
    return out


def _numeric_nonzero(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        try:
            return bool(math.isfinite(float(value)) and float(value) != 0.0)
        except (TypeError, ValueError):
            return False
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return False
        try:
            return float(s) != 0.0
        except ValueError:
            return False
    return False


def _metadata_velocity_indicators_nonzero(metadata: dict[str, Any]) -> bool:
    for key in _VELOCITY_INDICATOR_KEYS:
        if _numeric_nonzero(metadata.get(key)):
            return True
    nested = metadata.get("velocity_indicators")
    if isinstance(nested, dict):
        for val in nested.values():
            if _numeric_nonzero(val):
                return True
    return False


def _metadata_graph_indicators_nonzero(metadata: dict[str, Any]) -> bool:
    for key in _GRAPH_INDICATOR_KEYS:
        if _numeric_nonzero(metadata.get(key)):
            return True
    ip_vel = metadata.get("IP_VELOCITY")
    if isinstance(ip_vel, dict):
        if ip_vel.get("spike") is True:
            return True
        if _numeric_nonzero(ip_vel.get("distinct_users_last_2h")):
            return True
        if _numeric_nonzero(ip_vel.get("score")):
            return True
    return False


def _graph_signals_indicators_nonzero(graph_signals: dict[str, Any] | None) -> bool:
    if not isinstance(graph_signals, dict):
        return False
    if _numeric_nonzero(graph_signals.get("two_hop_distinct_cards_last_2h")):
        return True
    ip_vel = graph_signals.get("IP_VELOCITY")
    if isinstance(ip_vel, dict):
        if ip_vel.get("spike") is True:
            return True
        if _numeric_nonzero(ip_vel.get("distinct_users_last_2h")):
            return True
        if _numeric_nonzero(ip_vel.get("score")):
            return True
    degree = graph_signals.get("degree_centrality")
    if isinstance(degree, dict) and _numeric_nonzero(degree.get("total_distinct_neighbors")):
        return True
    clustering = graph_signals.get("clustering")
    if isinstance(clustering, dict):
        if _numeric_nonzero(clustering.get("accounts_sharing_three_devices")):
            return True
        if _numeric_nonzero(clustering.get("coefficient")):
            return True
    topology = graph_signals.get("graph_topology")
    if isinstance(topology, dict):
        if _numeric_nonzero(topology.get("blocked_device_touch_count")):
            return True
        if _numeric_nonzero(topology.get("neighbor_node_count")):
            return True
    return False


def velocity_indicators_nonzero(
    rule_data: dict[str, Any],
    transaction: TransactionSchema,
) -> bool:
    """True when transaction metadata or rule payload carries non-zero velocity signals."""
    if _numeric_nonzero(rule_data.get("risk_score")):
        return True
    meta = transaction.metadata if isinstance(transaction.metadata, dict) else {}
    return _metadata_velocity_indicators_nonzero(meta)


def _trend_watch_on_ingest_enabled() -> bool:
    raw = (os.environ.get("TREND_WATCH_ON_INGEST") or "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    # Default on when decision-api URL is configured (prod-like); else off.
    return bool((os.environ.get("DECISION_API_URL") or "").strip())


def _shadow_high_risk(shadow_data: dict[str, Any] | None) -> bool:
    if not isinstance(shadow_data, dict):
        return False
    if _shadow_data_is_timeout_fallback(shadow_data):
        return False
    try:
        risk = float(shadow_data.get("risk_score") or 0.0)
    except (TypeError, ValueError):
        risk = 0.0
    return bool(shadow_data.get("is_fraud")) or risk >= 75.0


async def maybe_enqueue_trend_watch(
    *,
    tenant_id: str,
    entity_id: str,
    reason: str,
    decision_api_url: str | None = None,
    http: httpx.AsyncClient | None = None,
) -> None:
    """Fire-and-forget watch upsert — never raises to callers."""
    if not _trend_watch_on_ingest_enabled():
        return
    base = (decision_api_url or os.environ.get("DECISION_API_URL") or "").strip()
    if not base or not tenant_id.strip() or not entity_id.strip():
        return
    url = f"{base.rstrip('/')}/v1/ops/trend/watch"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    api_key = (os.environ.get("API_KEYS") or "").split(",")[0].strip()
    if api_key:
        headers["x-api-key"] = api_key
    payload = {
        "tenant_id": tenant_id.strip(),
        "entity_id": entity_id.strip(),
        "reason": (reason or "")[:256],
    }
    try:
        if http is not None:
            await http.post(url, json=payload, headers=headers, timeout=2.0)
        else:
            async with httpx.AsyncClient(timeout=2.0) as client:
                await client.post(url, json=payload, headers=headers)
    except Exception:
        logger.warning(
            "orchestrator_trend_watch_enqueue_failed tenant_id=%s entity_id=%s",
            tenant_id,
            entity_id,
            exc_info=True,
        )


def graph_indicators_nonzero(
    rule_data: dict[str, Any],
    transaction: TransactionSchema,
    graph_signals: dict[str, Any] | None = None,
) -> bool:
    """True when metadata, prefetched graph signals, or matched graph rules show non-zero topology."""
    if rule_data.get("graph_context_fail_open") is True:
        return False
    meta = transaction.metadata if isinstance(transaction.metadata, dict) else {}
    if _metadata_graph_indicators_nonzero(meta):
        return True
    if _graph_signals_indicators_nonzero(graph_signals):
        return True
    trace = rule_data.get("evaluation_trace")
    if isinstance(trace, list):
        for row in trace:
            if not isinstance(row, dict) or not row.get("matched"):
                continue
            rule_name = str(row.get("rule_name") or "").lower()
            if "graph" in rule_name or "blocked" in rule_name or "device" in rule_name:
                return True
    return False


def should_invoke_shadow_synchronously(
    actions: list[str],
    rule_data: dict[str, Any],
    transaction: TransactionSchema,
    *,
    graph_signals: dict[str, Any] | None = None,
) -> bool:
    """
    Expand synchronous Shadow beyond explicit ``SHADOW_REVIEW``.

    Also invoke when ``FLAG`` is present **and** velocity or graph indicators are non-zero.
    """
    if "SHADOW_REVIEW" in actions:
        return True
    if "FLAG" not in actions:
        return False
    if velocity_indicators_nonzero(rule_data, transaction):
        return True
    return graph_indicators_nonzero(rule_data, transaction, graph_signals)


def _shadow_modulation_mode() -> str:
    """``escalate_only`` (default) | ``legacy`` | ``off``."""
    raw = (os.environ.get("SHADOW_ACTION_MODULATION") or "escalate_only").strip().lower()
    if raw in ("escalate_only", "legacy", "off"):
        return raw
    return "escalate_only"


def _shadow_data_is_timeout_fallback(shadow_data: dict[str, Any]) -> bool:
    if shadow_data.get("timeout_fallback") is True:
        return True
    metrics = shadow_data.get("confidence_metrics")
    if isinstance(metrics, dict) and metrics.get("timeout_fallback") is True:
        return True
    reasoning = shadow_data.get("reasoning")
    if isinstance(reasoning, list) and any(
        str(x).strip().upper() == "TIMEOUT_FALLBACK" for x in reasoning
    ):
        return True
    return False


def modulate_actions_with_shadow_advice(
    actions: list[str],
    shadow_data: dict[str, Any] | None,
) -> list[str]:
    """
    Apply Shadow structural advice (``risk_score``, ``is_fraud``) to outbound rule actions.

    Default mode ``escalate_only`` (``SHADOW_ACTION_MODULATION``): may add ``FLAG`` / drop
    ``ALLOW`` on high risk; never clears a deterministic ``FLAG`` to ``ALLOW``.
    Timeout / inconclusive Shadow responses leave FLAG/ALLOW unchanged.
    Never removes ``BLOCK``. Drops ``SHADOW_REVIEW`` once Shadow has returned advice
    (except timeout, where original actions including ``SHADOW_REVIEW`` are preserved).
    """
    if shadow_data is None:
        return list(actions)
    if "BLOCK" in actions:
        return list(actions)

    mode = _shadow_modulation_mode()
    if mode == "off" or _shadow_data_is_timeout_fallback(shadow_data):
        return list(actions)

    out = [a for a in actions if a != "SHADOW_REVIEW"]
    try:
        risk = float(shadow_data.get("risk_score", 0.0))
    except (TypeError, ValueError):
        risk = 0.0
    is_fraud = bool(shadow_data.get("is_fraud"))

    if is_fraud or risk >= 75.0:
        out = [a for a in out if a != "ALLOW"]
        if "FLAG" not in out:
            out.append("FLAG")
    elif mode == "legacy" and risk <= 25.0 and not is_fraud:
        # Opt-in only: historical FLAG→ALLOW downgrade (do not use in production).
        out = [a for a in out if a != "FLAG"]
        if not out:
            out = ["ALLOW"]
        elif "ALLOW" not in out:
            out.append("ALLOW")
    elif mode == "legacy":
        out = [a for a in out if a != "ALLOW"]
        if "FLAG" not in out:
            out.append("FLAG")
    # escalate_only + low/mid risk: keep deterministic FLAG/ALLOW; only SHADOW_REVIEW dropped

    return _dedupe_actions_preserve_order(out)


def _user_id_from_transaction(transaction: TransactionSchema) -> str | None:
    meta = transaction.metadata if isinstance(transaction.metadata, dict) else {}
    for key in ("user_id", "graph_user_id", "user"):
        raw = meta.get(key)
        if isinstance(raw, str) and raw.strip():
            s = raw.strip()
            if len(s) <= 512 and "\x00" not in s:
                return s
    return None


async def _prefetch_graph_signals_for_triage(
    graph_client: GraphClient | None,
    transaction: TransactionSchema,
) -> dict[str, Any] | None:
    if graph_client is None:
        return None
    uid = _user_id_from_transaction(transaction)
    if not uid:
        return None
    try:
        return await graph_client.get_graph_signals(uid)
    except Exception:
        logger.exception(
            "orchestrator_shadow_triage_graph_signals_failed transaction_id=%s",
            transaction.entity_id,
        )
        return None


async def _invoke_shadow_agent(
    *,
    client: httpx.AsyncClient,
    transaction: TransactionSchema,
    graph_client: GraphClient | None,
    shadow_base: str,
    shadow_key: str | None,
    shadow_read_s: float,
    shadow_http_timeout: httpx.Timeout,
    tid: str,
    actions: list[str],
    trigger: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Call Shadow ``POST /v1/analyze``; return ``(body, fallback_reason)``."""
    analyze_url = f"{shadow_base.rstrip('/')}/v1/analyze"
    headers: dict[str, str] = {}
    if shadow_key:
        headers["X-Shadow-Token"] = shadow_key
    logger.info(
        "orchestrator_shadow_downstream_post url=%s transaction_id=%s actions=%s trigger=%s",
        analyze_url,
        tid,
        actions,
        trigger,
    )
    try:
        shadow_body = await build_shadow_analyze_payload(transaction, graph_client)
        shadow_resp = await client.post(
            analyze_url,
            json=shadow_body,
            headers=headers or None,
            timeout=shadow_http_timeout,
        )
        shadow_resp.raise_for_status()
        body = shadow_resp.json()
        if not isinstance(body, dict):
            return None, "shadow_analyze_invalid_response_shape"
        return body, None
    except httpx.TimeoutException as exc:
        logger.warning(
            "orchestrator_shadow_analyze_deadline_exceeded url=%s transaction_id=%s "
            "deadline_s=%s exc=%s",
            analyze_url,
            tid,
            shadow_read_s,
            exc,
        )
        return None, "shadow_analyze_deadline_exceeded"
    except httpx.RequestError as exc:
        logger.warning(
            "orchestrator_shadow_sidecar_unreachable url=%s transaction_id=%s exc=%s",
            analyze_url,
            tid,
            exc,
        )
        return None, "SIDECAR_UNREACHABLE"


def _rule_eval_backend(request: Request) -> str:
    raw = getattr(request.app.state, "rule_eval_backend", None)
    if isinstance(raw, str) and raw.strip():
        return raw.strip().lower()
    return _RULE_EVAL_PYTHON


def _rule_eval_dual_run(request: Request) -> bool:
    return bool(getattr(request.app.state, "rule_eval_dual_run", False))


def _tenant_header_from_request(request: Request) -> str | None:
    return request.headers.get("X-Tenant-Id") or request.headers.get("x-tenant-id")


async def _rule_data_from_decision_api(
    *,
    client: httpx.AsyncClient,
    request: Request,
    transaction: TransactionSchema,
    tid: str,
) -> dict[str, Any]:
    decision_base = getattr(request.app.state, "decision_api_url", None)
    if not isinstance(decision_base, str) or not decision_base.strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "decision_api_url_required",
                "message": (
                    "decision-api evaluate requires DECISION_API_URL "
                    "(e.g. http://core-api:8000/decisions)."
                ),
            },
        )
    try:
        evaluate_body = map_tx_to_evaluate_request(
            transaction,
            tenant_header=_tenant_header_from_request(request),
        )
    except MissingTenantIdError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error": "tenant_id_required",
                "message": str(exc),
            },
        ) from exc
    evaluate = await post_decision_evaluate(
        client,
        decision_api_url=decision_base.strip(),
        body=evaluate_body,
    )
    return wire_rule_data_from_evaluate(evaluate, transaction_id=tid)


async def _rule_data_from_python(
    *,
    client: httpx.AsyncClient,
    rule_url: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    rule_response = await client.post(rule_url, json=payload)
    rule_response.raise_for_status()
    parsed = rule_response.json()
    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "rule_engine_invalid_response_shape",
                "type": type(parsed).__name__,
            },
        )
    return parsed


async def _maybe_dual_run_python_compare(
    *,
    client: httpx.AsyncClient,
    rule_url: str,
    payload: dict[str, Any],
    decision_rule_data: dict[str, Any],
    tid: str,
) -> dict[str, Any]:
    """Best-effort Python evaluate for diffs; never fails the ingest request."""
    try:
        python_rule_data = await _rule_data_from_python(
            client=client,
            rule_url=rule_url,
            payload=payload,
        )
    except Exception as exc:
        log_rule_eval_dual_run_diff(
            transaction_id=tid,
            diff={},
            python_error=f"{type(exc).__name__}: {exc}",
        )
        return {
            "python_ok": False,
            "python_error": f"{type(exc).__name__}: {exc}",
            "side_effects": "decision_api",
        }

    diff = compare_rule_eval_outcomes(
        decision_api_rule_data=decision_rule_data,
        python_rule_data=python_rule_data,
    )
    log_rule_eval_dual_run_diff(transaction_id=tid, diff=diff)
    return {
        "python_ok": True,
        "side_effects": "decision_api",
        **diff,
    }


async def execute_transaction_ingest(
    *,
    request: Request,
    transaction: TransactionSchema,
) -> dict[str, Any]:
    """Run ``/v1/ingest`` policy + optional Shadow + durable audit rows for one envelope."""
    payload = transaction.model_dump(mode="json")
    tid = str(transaction.entity_id)
    backend = _rule_eval_backend(request)
    dual_run = _rule_eval_dual_run(request)
    # Dual-run prefers decision-api for side effects (Phase 1).
    use_decision_api = dual_run or backend == _RULE_EVAL_DECISION_API
    rule_url = f"{request.app.state.rule_engine_url}/v1/evaluate"
    rule_timeout = httpx.Timeout(30.0, connect=10.0)
    shadow_read_s = float(request.app.state.shadow_analyze_timeout_seconds)
    shadow_http_timeout = httpx.Timeout(shadow_read_s, connect=min(5.0, shadow_read_s))
    shadow_base_st: str | None = request.app.state.shadow_agent_url
    shadow_key_st: str | None = request.app.state.shadow_api_key
    actions: list[str] = []
    rule_data: dict[str, Any]

    gc = getattr(request.app.state, "graph_client", None)

    shadow_data: dict[str, Any] | None = None
    shadow_fallback_reason: str | None = None
    shadow_sync_invoked = False
    shadow_sync_trigger: str | None = None

    try:
        async with httpx.AsyncClient(timeout=rule_timeout) as client:
            if use_decision_api:
                rule_data = await _rule_data_from_decision_api(
                    client=client,
                    request=request,
                    transaction=transaction,
                    tid=tid,
                )
                if dual_run:
                    dual_meta = await _maybe_dual_run_python_compare(
                        client=client,
                        rule_url=rule_url,
                        payload=payload,
                        decision_rule_data=rule_data,
                        tid=tid,
                    )
                    rule_data = {**rule_data, "rule_eval_dual_run": dual_meta}
            else:
                rule_data = await _rule_data_from_python(
                    client=client,
                    rule_url=rule_url,
                    payload=payload,
                )

            actions = actions_from_rule_payload(rule_data)
            sdn_client = getattr(request.app.state, "shadow_dispatch_nats", None)
            try:
                await dispatch_shadow_investigate_if_review(
                    sdn_client,
                    entity_id=tid,
                    metadata=dict(transaction.metadata),
                    rule_data=rule_data,
                    actions=actions,
                    transaction=transaction,
                )
            except Exception:
                logger.exception(
                    "orchestrator_shadow_dispatch_nats_publish_failed transaction_id=%s",
                    tid,
                )

            graph_signals = await _prefetch_graph_signals_for_triage(gc, transaction)
            shadow_sync_invoked = should_invoke_shadow_synchronously(
                actions,
                rule_data,
                transaction,
                graph_signals=graph_signals,
            )
            if shadow_sync_invoked:
                if "SHADOW_REVIEW" in actions:
                    shadow_sync_trigger = "SHADOW_REVIEW"
                else:
                    shadow_sync_trigger = "FLAG_ELEVATED_TRIAGE"
                if not shadow_base_st:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail={
                            "error": "shadow_agent_url_required",
                            "message": (
                                "Shadow sidecar URL is required when SHADOW_REVIEW or "
                                "FLAG+velocity/graph triage applies."
                            ),
                        },
                    )
                shadow_data, shadow_fallback_reason = await _invoke_shadow_agent(
                    client=client,
                    transaction=transaction,
                    graph_client=gc,
                    shadow_base=shadow_base_st,
                    shadow_key=shadow_key_st,
                    shadow_read_s=shadow_read_s,
                    shadow_http_timeout=shadow_http_timeout,
                    tid=tid,
                    actions=actions,
                    trigger=shadow_sync_trigger,
                )
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

    original_actions = list(actions)
    if shadow_sync_invoked and shadow_data is not None:
        modulation_mode = _shadow_modulation_mode()
        actions = modulate_actions_with_shadow_advice(actions, shadow_data)
        rule_data = {
            **rule_data,
            "actions": actions,
            "shadow_action_modulation": {
                "trigger": shadow_sync_trigger,
                "mode": modulation_mode,
                "timeout_fallback": _shadow_data_is_timeout_fallback(shadow_data),
                "original_actions": original_actions,
                "modulated_actions": actions,
                "shadow_risk_score": shadow_data.get("risk_score"),
                "shadow_is_fraud": shadow_data.get("is_fraud"),
            },
        }

    # Best-effort trend watch enqueue (never blocks / fails ingest).
    try:
        entity_for_watch = (
            _user_id_from_transaction(transaction)
            or str(getattr(transaction, "entity_id", "") or "").strip()
            or tid
        )
        tenant_for_watch = str(
            (transaction.metadata or {}).get("tenant_id")
            or getattr(transaction, "tenant_id", "")
            or ""
        ).strip()
        if not tenant_for_watch and isinstance(rule_data.get("tenant_id"), str):
            tenant_for_watch = rule_data["tenant_id"].strip()
        should_watch = _shadow_high_risk(shadow_data) or velocity_indicators_nonzero(
            rule_data, transaction
        )
        if should_watch and tenant_for_watch:
            reasons: list[str] = []
            if _shadow_high_risk(shadow_data):
                reasons.append("shadow_high_risk")
            if velocity_indicators_nonzero(rule_data, transaction):
                reasons.append("velocity_indicators")
            decision_base = getattr(request.app.state, "decision_api_url", None)
            await maybe_enqueue_trend_watch(
                tenant_id=tenant_for_watch,
                entity_id=str(entity_for_watch),
                reason=",".join(reasons),
                decision_api_url=str(decision_base) if decision_base else None,
            )
    except Exception:
        logger.warning("orchestrator_trend_watch_hook_failed transaction_id=%s", tid, exc_info=True)

    shadow_matches: list[dict[str, Any]] = []
    try:
        shadow_matches = await evaluate_transaction_shadow_matches(request.app.state, transaction)
    except Exception:
        logger.exception("orchestrator_shadow_hypothesis_eval_failed transaction_id=%s", tid)

    fac = getattr(request.app.state, "audit_session_factory", None)
    if fac is None:
        _raise_audit_persistence_http(AuditPersistenceError.unconfigured())

    try:
        orchestrator_audit_log_id: int | None = None
        async with atomic_transaction(fac) as session:
            await persist_lekh_decision(session, entity_id=tid, rule_data=rule_data)
            orchestrator_audit_log_id = await persist_orchestrator_audit_log(
                session,
                entity_id=tid,
                metadata=dict(transaction.metadata),
                actions=actions,
                rule_data=rule_data,
                shadow_data=shadow_data,
                shadow_matches=shadow_matches,
                transaction_envelope=_transaction_envelope_for_audit(transaction),
            )
            await OutboxDAO.create_task(
                session,
                OUTBOX_EVENT_GRAPH_INGEST,
                _graph_ingest_outbox_idempotency_key(tid, orchestrator_audit_log_id),
                _graph_ingest_outbox_payload(
                    transaction=transaction,
                    rule_data=rule_data,
                    audit_log_id=orchestrator_audit_log_id,
                ),
            )
            await OutboxDAO.create_task(
                session,
                OUTBOX_EVENT_VELOCITY_UPDATE,
                _velocity_update_outbox_idempotency_key(tid, orchestrator_audit_log_id),
                _velocity_update_outbox_payload(transaction=transaction),
            )
    except AuditPersistenceError as exc:
        logger.exception(
            "orchestrator_lekh_or_audit_persist_failed transaction_id=%s",
            tid,
        )
        _raise_audit_persistence_http(exc)
    except TarkaDatabaseException as exc:
        logger.exception(
            "orchestrator_ingest_atomic_transaction_failed transaction_id=%s error_code=%s",
            tid,
            exc.error_code,
        )
        _raise_database_transaction_http(exc, entity_id=tid)
    except Exception:
        logger.exception(
            "orchestrator_lekh_or_audit_persist_failed transaction_id=%s",
            tid,
        )
        _raise_audit_persistence_http(
            AuditPersistenceError.persist_failed(entity_id=tid, component="orchestrator"),
        )

    autoresolve_outcome: dict[str, Any] | None = None
    if shadow_data is not None and orchestrator_audit_log_id is not None:
        gc: GraphClient = request.app.state.graph_client
        ar = await try_shadow_autoresolve_after_ingest(
            audit_session_factory=fac,
            graph_client=gc,
            audit_log_id=orchestrator_audit_log_id,
            entity_id=tid,
            metadata=dict(transaction.metadata),
            actions=actions,
            rule_data=rule_data,
            shadow_data=shadow_data,
            auth_token=resolve_autoresolve_auth_token(),
            lifecycle_actions=original_actions if shadow_sync_invoked else actions,
        )
        autoresolve_outcome = {
            "attempted": ar.attempted,
            "lifecycle_case_id": ar.lifecycle_case_id,
            "confidence": ar.confidence,
            "skipped_reason": ar.skipped_reason,
        }
        if ar.transition is not None:
            autoresolve_outcome["status"] = ar.transition.get("status")
            autoresolve_outcome["transition_audit_log_id"] = ar.transition.get("audit_log_id")

    out: dict[str, Any] = {
        "risk_decision": finalize_live_evaluation_wire_payload(rule_data),
        "transaction_id": tid,
    }
    if shadow_sync_trigger:
        out["shadow_sync_trigger"] = shadow_sync_trigger
    if shadow_data is not None:
        out["shadow_agent"] = shadow_data
    if autoresolve_outcome is not None:
        out["shadow_autoresolve"] = autoresolve_outcome
    elif shadow_sync_invoked and shadow_base_st and shadow_fallback_reason:
        out["orchestrator_fallback_decision"] = "FLAG"
        out["orchestrator_fallback_reason"] = shadow_fallback_reason
        if shadow_fallback_reason == "shadow_analyze_deadline_exceeded":
            out["orchestrator_shadow_deadline_seconds"] = shadow_read_s
    return out
