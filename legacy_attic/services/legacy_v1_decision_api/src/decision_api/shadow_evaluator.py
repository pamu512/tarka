"""Parallel Production vs Candidate JSON rule evaluation (shadow orchestrator).

For each evaluate request (when enabled), runs **Production** (active packs) and **Candidate**
(disk-backed packs under ``CANDIDATE_RULES_PATH``) concurrently via ``asyncio.gather`` bounded by
``asyncio.wait_for``. Only the Production tuple drives the HTTP response; both outcomes are
persisted to ClickHouse when configured.

DDL (operators create explicitly; names match ``settings.clickhouse_shadow_evaluations_table``)::

    CREATE TABLE IF NOT EXISTS shadow_rule_evaluations (
      event_time DateTime64(3, 'UTC') DEFAULT now64(3),
      trace_id String,
      tenant_id String,
      entity_id String,
      production_json String,
      candidate_json String,
      timed_out UInt8
    ) ENGINE = MergeTree ORDER BY (tenant_id, event_time);
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from clickhouse_connect.driver.client import Client
from fastapi import HTTPException, Request

from decision_api.config import Settings
from decision_api.deps import run_clickhouse_sync
from decision_api.json_rules import (
    evaluate_adhoc_packs_json,
    evaluate_json_rules,
    get_json_rule_engine_metadata,
)
from decision_api.rust_rule_engine_exceptions import (
    RustRuleEngineCircuitOpenError,
    RustRuleEngineInvocationFailed,
)
from tarka_core.internal_monitor import InternalMonitor

log = logging.getLogger("decision-api.shadow_evaluator")

_candidate_packs: list[dict[str, Any]] = []
_candidate_enabled: bool = False


def load_candidate_rules() -> None:
    """Load candidate rule packs from ``settings.candidate_rules_path`` (JSON files)."""
    global _candidate_packs, _candidate_enabled
    from decision_api.config import settings

    path = (settings.candidate_rules_path or "").strip()
    if not path or not os.path.isdir(path):
        _candidate_packs = []
        _candidate_enabled = False
        return
    packs: list[dict[str, Any]] = []
    for fname in sorted(os.listdir(path)):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(path, fname), encoding="utf-8") as f:
                pack = json.load(f)
            packs.append(pack)
        except OSError as e:
            log.warning("candidate_rules_read_failed file=%s err=%s", fname, e)
        except json.JSONDecodeError as e:
            log.warning("candidate_rules_json_invalid file=%s err=%s", fname, e)
    _candidate_packs = packs
    _candidate_enabled = len(_candidate_packs) > 0
    log.info(
        "Loaded %d candidate rule pack(s) from %s",
        len(_candidate_packs),
        path,
    )


def candidate_rules_available() -> bool:
    return _candidate_enabled and bool(_candidate_packs)


def _evaluate_json_rules_http_equivalent(
    features: dict[str, Any],
    redis_tag_list: list[str],
    tenant_id: str,
    entity_id: str,
    *,
    evaluation_mode: str,
    signal_tags: list[str],
) -> tuple[list[str], list[str], float, list[str], dict[str, Any]]:
    """Mirror ``main._evaluate_json_rules_http`` (circuit breaker → HTTP or emergency static)."""
    from decision_api.config import settings
    from decision_api.json_rules import build_emergency_static_rule_tuple

    try:
        rule_hits, rule_tags, score_delta, pack_files = evaluate_json_rules(
            features,
            redis_tag_list,
            tenant_id,
            entity_id,
            evaluation_mode=evaluation_mode,
            signal_tags=signal_tags,
        )
        return (
            rule_hits,
            rule_tags,
            score_delta,
            pack_files,
            get_json_rule_engine_metadata(),
        )
    except RustRuleEngineCircuitOpenError as e:
        if (
            getattr(settings, "rust_ffi_circuit_open_behavior", "503")
            == "emergency_static"
        ):
            h, t, d, pf = build_emergency_static_rule_tuple()
            meta = {
                "engine": "emergency_static",
                "fallback_active": True,
                "rust_ffi_circuit_open": True,
                "failures_in_window": e.failures_in_window,
            }
            return h, t, d, pf, meta
        raise HTTPException(
            status_code=503,
            detail={
                "error": "rust_ffi_circuit_open",
                "message": "JSON rule engine circuit is open after repeated Rust FFI failures.",
                "failures_in_window": e.failures_in_window,
            },
        ) from e
    except RustRuleEngineInvocationFailed as e:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "rust_rule_engine_failed",
                "message": "Rust JSON rule engine evaluation failed.",
                "exc_type": type(e.cause).__name__
                if getattr(e, "cause", None)
                else type(e).__name__,
            },
        ) from e


def _evaluate_candidate_sync(
    features: dict[str, Any],
    redis_tag_list: list[str],
    tenant_id: str,
    entity_id: str,
    signal_tags: list[str],
) -> dict[str, Any]:
    """Evaluate candidate packs; never raises HTTPException — errors become JSON-serializable dict."""
    if not _candidate_packs:
        return {"skipped": True, "reason": "no_candidate_packs_loaded"}

    try:
        hits, tags, delta, pack_files = evaluate_adhoc_packs_json(
            list(_candidate_packs),
            features,
            redis_tag_list,
            tenant_id,
            entity_id,
            evaluation_mode="simulation",
            record_telemetry=False,
            signal_tags=signal_tags,
        )
    except (RustRuleEngineCircuitOpenError, RustRuleEngineInvocationFailed) as e:
        return {
            "error": type(e).__name__,
            "detail": repr(e),
            "candidate_eval_failed": True,
        }

    cand_score = max(0.0, min(100.0, 10.0 + delta))
    if cand_score >= 80:
        cand_decision = "deny"
    elif cand_score >= 50:
        cand_decision = "review"
    else:
        cand_decision = "allow"

    return {
        "candidate_decision": cand_decision,
        "candidate_score": cand_score,
        "candidate_rule_hits": hits,
        "candidate_tags": tags,
        "candidate_score_delta": delta,
        "candidate_pack_files": pack_files,
    }


def _production_tuple_to_audit_dict(
    tup: tuple[list[str], list[str], float, list[str], dict[str, Any]],
) -> dict[str, Any]:
    hits, tags, delta, packs, meta = tup
    base = 10.0 + delta
    score = max(0.0, min(100.0, base))
    if score >= 80:
        dec = "deny"
    elif score >= 50:
        dec = "review"
    else:
        dec = "allow"
    return {
        "production_decision": dec,
        "production_score": score,
        "production_rule_hits": hits,
        "production_tags": tags,
        "production_score_delta": delta,
        "production_pack_files": packs,
        "engine_meta": meta,
    }


def _clickhouse_insert_sync(
    client: Client,
    *,
    table: str,
    trace_id: str,
    tenant_id: str,
    entity_id: str,
    production: dict[str, Any],
    candidate: dict[str, Any],
    timed_out: bool,
) -> None:
    row = [
        trace_id,
        tenant_id,
        entity_id,
        json.dumps(production, separators=(",", ":"), default=str),
        json.dumps(candidate, separators=(",", ":"), default=str),
        1 if timed_out else 0,
    ]
    client.insert(
        table,
        [row],
        column_names=[
            "trace_id",
            "tenant_id",
            "entity_id",
            "production_json",
            "candidate_json",
            "timed_out",
        ],
    )


async def _persist_shadow_eval_clickhouse(
    request: Request,
    *,
    settings: Settings,
    trace_id: str,
    tenant_id: str,
    entity_id: str,
    production_record: dict[str, Any],
    candidate_record: dict[str, Any],
    timed_out: bool,
) -> None:
    table = (settings.clickhouse_shadow_evaluations_table or "").strip()
    ch = getattr(request.app.state, "clickhouse_client", None)
    if ch is None or not table:
        return

    async def _run() -> None:
        _clickhouse_insert_sync(
            ch,
            table=table,
            trace_id=trace_id,
            tenant_id=tenant_id,
            entity_id=entity_id,
            production=production_record,
            candidate=candidate_record,
            timed_out=timed_out,
        )

    try:
        await run_clickhouse_sync(ch, _run)
    except Exception as exc:
        InternalMonitor.log_suppressed_error(
            exc,
            context="shadow_evaluator_clickhouse_insert",
            domain="analytics",
        )


class ShadowEvaluator:
    """Runs Production and Candidate JSON rule evaluations in parallel for shadow comparison."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def evaluate_parallel(
        self,
        *,
        request: Request,
        features: dict[str, Any],
        redis_tag_list: list[str],
        tenant_id: str,
        entity_id: str,
        signal_tags: list[str],
        trace_id: str,
    ) -> tuple[list[str], list[str], float, list[str], dict[str, Any]]:
        """Return Production rule-engine tuple (same contract as ``_evaluate_json_rules_http``).

        Candidate outcome is logged to ClickHouse and never affects the returned tuple.
        """
        timeout_s = float(self._settings.shadow_evaluator_timeout_seconds)

        async def run_prod() -> tuple[list[str], list[str], float, list[str], dict[str, Any]]:
            return await asyncio.to_thread(
                _evaluate_json_rules_http_equivalent,
                features,
                redis_tag_list,
                tenant_id,
                entity_id,
                evaluation_mode="production",
                signal_tags=signal_tags,
            )

        async def run_cand() -> dict[str, Any]:
            return await asyncio.to_thread(
                _evaluate_candidate_sync,
                features,
                redis_tag_list,
                tenant_id,
                entity_id,
                signal_tags,
            )

        cand_placeholder: dict[str, Any] = {"skipped": True, "reason": "not_run"}
        timed_out = False

        try:
            prod_out, cand_out = await asyncio.wait_for(
                asyncio.gather(
                    run_prod(),
                    run_cand(),
                    return_exceptions=True,
                ),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            timed_out = True
            log.warning(
                "shadow_evaluator_timeout trace_id=%s timeout_s=%s",
                trace_id,
                timeout_s,
            )
            prod_out = await asyncio.to_thread(
                _evaluate_json_rules_http_equivalent,
                features,
                redis_tag_list,
                tenant_id,
                entity_id,
                evaluation_mode="production",
                signal_tags=signal_tags,
            )
            cand_out = {
                "timeout": True,
                "reason": f"gather exceeded {timeout_s}s",
            }

        if isinstance(prod_out, BaseException):
            raise prod_out
        if not isinstance(prod_out, tuple):
            raise RuntimeError("shadow_evaluator: internal production result malformed")

        if isinstance(cand_out, BaseException):
            cand_placeholder = {
                "error": type(cand_out).__name__,
                "detail": repr(cand_out),
            }
        elif isinstance(cand_out, dict):
            cand_placeholder = cand_out
        else:
            cand_placeholder = {"error": "unexpected_candidate_result"}

        prod_audit = _production_tuple_to_audit_dict(prod_out)
        await _persist_shadow_eval_clickhouse(
            request,
            settings=self._settings,
            trace_id=trace_id,
            tenant_id=tenant_id,
            entity_id=entity_id,
            production_record=prod_audit,
            candidate_record=cand_placeholder,
            timed_out=timed_out,
        )

        return prod_out
