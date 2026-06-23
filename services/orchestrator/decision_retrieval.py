"""Assemble analyst decision detail from Lekh ``decisions`` + ``audit_logs`` rows."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tarka_shared.audit_trail import AuditLog

from audit_case_worker import ORCHESTRATOR_AUDIT_SOURCE
from models.decision import DecisionORM

logger = logging.getLogger(__name__)

_UI_CHANNELS = frozenset({"card_not_present", "card_present", "ach", "wire"})
_SHADOW_MODEL_ID = "shadow-agent"


def _parse_json_dict(raw: str | None) -> dict[str, Any] | None:
    if raw is None or not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _is_shadow_decision_dict(d: dict[str, Any]) -> bool:
    return (
        "risk_score" in d
        and "is_fraud" in d
        and isinstance(d.get("reasoning"), list)
        and "transaction_id" in d
    )


def _coerce_channel(raw: Any) -> str:
    s = str(raw or "").strip()
    if s in _UI_CHANNELS:
        return s
    return "card_not_present"


def _metadata_scalar_map(meta: Any) -> dict[str, str | int | bool]:
    if not isinstance(meta, dict):
        return {}
    out: dict[str, str | int | bool] = {}
    for k, v in meta.items():
        if isinstance(v, (str, int, bool)):
            out[str(k)] = v
    return out


def ui_transaction_schema_from_envelope(
    *,
    transaction_id: str,
    envelope: dict[str, Any] | None,
) -> dict[str, Any]:
    """Map ingest ``TransactionSchema`` envelope (+ metadata) to UI ``TransactionSchema``."""
    meta = envelope.get("metadata") if isinstance(envelope, dict) else None
    meta_map = _metadata_scalar_map(meta)
    amount = 0.0
    if isinstance(envelope, dict):
        try:
            amount = float(envelope.get("amount") or 0.0)
        except (TypeError, ValueError):
            amount = 0.0
    amount_cents = max(0, int(round(amount * 100)))
    channel = _coerce_channel(meta_map.get("channel") if meta_map else None)
    merchant_id = str(meta_map.get("merchant_id") or meta_map.get("merchantId") or "unknown")
    fingerprint = str(
        meta_map.get("instrument_fingerprint")
        or meta_map.get("device_fingerprint")
        or meta_map.get("device_id")
        or f"fp_{transaction_id[-12:]}"
    )
    ip_asn = str(meta_map.get("ip_asn") or meta_map.get("asn") or "unknown")
    geo = str(
        (envelope or {}).get("country")
        or meta_map.get("geo_country")
        or meta_map.get("country")
        or "ZZ"
    )
    mcc = str(meta_map.get("mcc") or "0000")
    velocity_window = meta_map.get("velocity_window_minutes")
    prior_declines = meta_map.get("prior_declines_24h")
    return {
        "schema_version": "v2.1",
        "transaction_id": transaction_id,
        "amount_cents": amount_cents,
        "currency": str(meta_map.get("currency") or "USD"),
        "channel": channel,
        "merchant_id": merchant_id,
        "instrument_fingerprint": fingerprint,
        "ip_asn": ip_asn,
        "geo_country": geo[:8] if geo else "ZZ",
        "mcc": mcc,
        "velocity_window_minutes": (
            int(velocity_window) if isinstance(velocity_window, (int, float)) else 15
        ),
        "prior_declines_24h": (
            int(prior_declines) if isinstance(prior_declines, (int, float)) else 0
        ),
        "metadata": meta_map,
    }


def ui_shadow_decision_from_agent(
    shadow: dict[str, Any],
    *,
    final_decision: str | None = None,
) -> dict[str, Any]:
    """Map Shadow agent JSON to UI ``ShadowDecision``."""
    try:
        risk = float(shadow.get("risk_score") or 0.0)
    except (TypeError, ValueError):
        risk = 0.0
    is_fraud = bool(shadow.get("is_fraud"))
    if is_fraud:
        verdict = "fraud"
    elif risk >= 70.0:
        verdict = "elevated_risk"
    elif risk >= 40.0:
        verdict = "review"
    elif final_decision:
        verdict = final_decision.lower()
    else:
        verdict = "clear"
    reasoning = shadow.get("reasoning")
    risk_tags = (
        [str(x) for x in reasoning if isinstance(x, str) and x.strip()][:8]
        if isinstance(reasoning, list)
        else []
    )
    conf_metrics = shadow.get("confidence_metrics")
    counterfactuals = 0
    if isinstance(conf_metrics, dict):
        for key in ("counterfactuals_considered", "counterfactuals", "scenarios_considered"):
            raw = conf_metrics.get(key)
            if isinstance(raw, (int, float)):
                counterfactuals = max(0, int(raw))
                break
    if counterfactuals == 0 and isinstance(reasoning, list):
        counterfactuals = len(reasoning)
    latency_ms = 0
    debug = shadow.get("_debug")
    if isinstance(debug, dict):
        raw_lat = debug.get("latency_ms")
        if isinstance(raw_lat, (int, float)):
            latency_ms = max(0, int(raw_lat))
    ai_reasoning = shadow.get("ai_reasoning")
    if ai_reasoning is None and isinstance(reasoning, list):
        ai_reasoning = reasoning
    return {
        "model_id": str(shadow.get("model_id") or _SHADOW_MODEL_ID),
        "shadow_verdict": verdict,
        "confidence": min(1.0, max(0.0, risk / 100.0)),
        "risk_tags": risk_tags,
        "ai_reasoning": ai_reasoning if ai_reasoning is not None else "",
        "latency_ms": latency_ms,
        "counterfactuals_considered": counterfactuals,
    }


def _fallback_shadow_decision(final_decision: str) -> dict[str, Any]:
    fd = (final_decision or "NONE").strip().upper()
    verdict = fd.lower() if fd else "unknown"
    return {
        "model_id": _SHADOW_MODEL_ID,
        "shadow_verdict": verdict,
        "confidence": 0.0,
        "risk_tags": [],
        "ai_reasoning": "Shadow analysis was not persisted for this transaction.",
        "latency_ms": 0,
        "counterfactuals_considered": 0,
    }


async def fetch_decision_detail_payload(
    audit_session_factory: async_sessionmaker[AsyncSession] | None,
    *,
    transaction_id: str,
) -> dict[str, Any] | None:
    """
    Return UI-shaped decision detail or ``None`` when the transaction is not materialized yet.
    """
    if audit_session_factory is None:
        return None

    tid = (transaction_id or "").strip()
    try:
        uuid.UUID(tid)
    except ValueError:
        return None

    async with audit_session_factory() as session:
        decision_row = (
            await session.execute(
                select(DecisionORM)
                .where(DecisionORM.entity_id == tid)
                .order_by(DecisionORM.created_at.desc(), DecisionORM.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        audit_rows = (
            (
                await session.execute(
                    select(AuditLog)
                    .where(AuditLog.case_id == tid)
                    .order_by(AuditLog.id.desc())
                    .limit(32)
                )
            )
            .scalars()
            .all()
        )

    if decision_row is None and not audit_rows:
        return None

    envelope: dict[str, Any] | None = None
    shadow_raw: dict[str, Any] | None = None

    for row in audit_rows:
        body = _parse_json_dict(row.action_taken)
        if body is None:
            continue
        if body.get("source") == ORCHESTRATOR_AUDIT_SOURCE:
            tx_env = body.get("transaction_envelope")
            if isinstance(tx_env, dict):
                envelope = tx_env
        if shadow_raw is None:
            notes = _parse_json_dict(row.agent_notes)
            if notes is not None and _is_shadow_decision_dict(notes):
                shadow_raw = notes

    final_decision = decision_row.final_decision if decision_row is not None else "NONE"
    trace: list[Any] = []
    if decision_row is not None:
        if isinstance(decision_row.execution_trace_json, list):
            trace = decision_row.execution_trace_json
        elif isinstance(decision_row.raw_rule_engine_json, dict):
            raw_trace = decision_row.raw_rule_engine_json.get("evaluation_trace")
            if isinstance(raw_trace, list):
                trace = raw_trace

    if (
        envelope is None
        and decision_row is not None
        and isinstance(decision_row.raw_rule_engine_json, dict)
    ):
        raw_tx = decision_row.raw_rule_engine_json.get("transaction")
        if isinstance(raw_tx, dict):
            envelope = raw_tx

    transaction_schema = ui_transaction_schema_from_envelope(
        transaction_id=tid,
        envelope=envelope,
    )

    if shadow_raw is not None:
        shadow_decision = ui_shadow_decision_from_agent(shadow_raw, final_decision=final_decision)
    else:
        shadow_decision = _fallback_shadow_decision(final_decision)

    out: dict[str, Any] = {
        "transaction_schema": transaction_schema,
        "shadow_decision": shadow_decision,
    }
    if trace:
        out["evaluation_trace"] = trace
    return out
