"""Map TransactionSchema ↔ decision-api evaluate (Approach A, action_map_v1)."""

from __future__ import annotations

import logging
import os
from typing import Any, Mapping, Protocol

import httpx

logger = logging.getLogger(__name__)

ACTION_MAP_V1 = "action_map_v1"

_VALID_EVENT_TYPES: frozenset[str] = frozenset(
    {"login", "payment", "signup", "device", "session", "custom"},
)

_CHALLENGE_RECOMMENDED: frozenset[str] = frozenset(
    {
        "challenge",
        "step_up",
        "step_up_mfa",
        "step_up_attestation",
        "step-up",
        "step-up-mfa",
        "step-up-attestation",
    },
)

_SHADOW_RULE_PREFIX = "shadow:"


class MissingTenantIdError(ValueError):
    """Raised when neither metadata nor X-Tenant-Id supplies a tenant."""


class _TransactionEnvelope(Protocol):
    """Minimal envelope surface used by the evaluate map (TransactionSchema-compatible)."""

    entity_id: Any
    amount: Any
    timestamp: Any
    metadata: Mapping[str, Any]
    country: Any


def resolve_tenant_id(
    metadata: Mapping[str, Any],
    *,
    tenant_header: str | None,
) -> str:
    """Require tenant from metadata.tenant_id or trusted X-Tenant-Id."""
    raw = metadata.get("tenant_id")
    if isinstance(raw, str):
        token = raw.strip()
        if token:
            return token
    if tenant_header is not None:
        header = tenant_header.strip()
        if header:
            return header
    raise MissingTenantIdError(
        "tenant_id is required (metadata.tenant_id or X-Tenant-Id); refusing evaluate",
    )


def resolve_event_type(metadata: Mapping[str, Any]) -> str:
    raw = metadata.get("event_type")
    if isinstance(raw, str):
        token = raw.strip().lower()
        if token in _VALID_EVENT_TYPES:
            return token
    return "payment"


def _meta_str(meta: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        raw = meta.get(key)
        if isinstance(raw, str):
            token = raw.strip()
            if token:
                return token
    return None


def _device_context_from_metadata(meta: Mapping[str, Any]) -> dict[str, Any] | None:
    device_id = _meta_str(meta, "device_id", "deviceId")
    if not device_id:
        return None
    platform = _meta_str(meta, "device_platform", "platform") or "web"
    signals: dict[str, Any] = {}
    for key, value in meta.items():
        if not isinstance(key, str):
            continue
        if key.startswith("device_") and key not in {"device_id", "device_platform"}:
            signals[key] = value
    out: dict[str, Any] = {"device_id": device_id, "platform": platform, "signals": signals}
    return out


def map_tx_to_evaluate_request(
    transaction: _TransactionEnvelope,
    *,
    tenant_header: str | None = None,
) -> dict[str, Any]:
    """Pure map: transaction envelope → decision-api EvaluateRequest JSON body."""
    meta = dict(transaction.metadata) if isinstance(transaction.metadata, dict) else {}
    tenant_id = resolve_tenant_id(meta, tenant_header=tenant_header)
    event_type = resolve_event_type(meta)

    ts = transaction.timestamp
    ts_iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)

    payload: dict[str, Any] = {
        "amount": float(transaction.amount),
        "timestamp": ts_iso,
    }
    if transaction.country is not None:
        payload["country"] = transaction.country
    # Pass through non-reserved metadata keys into payload for rule features.
    reserved = {"tenant_id", "event_type", "session_id", "region", "device_id", "device_platform"}
    for key, value in meta.items():
        if key in reserved or key in payload:
            continue
        payload[key] = value

    body: dict[str, Any] = {
        "tenant_id": tenant_id,
        "event_type": event_type,
        "entity_id": str(transaction.entity_id),
        "session_id": _meta_str(meta, "session_id", "device_session_id", "anumana_session_id"),
        "region": _meta_str(meta, "region") or "global",
        "payload": payload,
        "metadata": meta,
    }
    device_ctx = _device_context_from_metadata(meta)
    if device_ctx is not None:
        body["device_context"] = device_ctx
    return body


def _dedupe_preserve(actions: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for action in actions:
        if action not in seen:
            seen.add(action)
            out.append(action)
    return out


def map_evaluate_to_actions(evaluate: Mapping[str, Any]) -> list[str]:
    """action_map_v1: decision-api decision → orchestrator actions[]."""
    decision = str(evaluate.get("decision") or "").strip().lower()
    if decision == "deny":
        actions = ["BLOCK"]
    elif decision == "review":
        actions = ["SHADOW_REVIEW", "FLAG"]
    elif decision == "allow":
        actions = ["ALLOW"]
    else:
        # Unknown decision: fail closed to FLAG so ingest remains auditable.
        logger.warning(
            "decision_evaluate_bridge_unknown_decision decision=%s; defaulting to FLAG",
            decision,
        )
        actions = ["FLAG"]

    recommended = evaluate.get("recommended_action")
    if isinstance(recommended, str):
        rec = recommended.strip().lower().replace(" ", "_")
        if (
            rec in _CHALLENGE_RECOMMENDED
            or rec.startswith("step_up")
            or rec.startswith("challenge")
        ):
            if "FLAG" not in actions:
                actions.append("FLAG")

    tags = evaluate.get("tags")
    if isinstance(tags, list) and any(str(t).strip().lower() == "shadow_review" for t in tags):
        if "SHADOW_REVIEW" not in actions:
            actions.append("SHADOW_REVIEW")

    hits = evaluate.get("rule_hits")
    if isinstance(hits, list):
        for hit in hits:
            if isinstance(hit, str) and hit.strip().lower().startswith(_SHADOW_RULE_PREFIX):
                if "SHADOW_REVIEW" not in actions:
                    actions.append("SHADOW_REVIEW")
                break

    if decision == "deny" and "BLOCK" not in actions:
        actions.insert(0, "BLOCK")

    return _dedupe_preserve(actions)


def blocking_rule_id_from_evaluate(evaluate: Mapping[str, Any], actions: list[str]) -> str | None:
    if "BLOCK" not in actions:
        return None
    hits = evaluate.get("rule_hits")
    if isinstance(hits, list):
        for hit in hits:
            if isinstance(hit, str) and hit.strip():
                return hit.strip()[:128]
            if isinstance(hit, dict):
                rid = hit.get("rule_id") or hit.get("id")
                if rid is not None and str(rid).strip():
                    return str(rid).strip()[:128]
    return "decision_api_deny"


def evaluation_trace_from_evaluate(evaluate: Mapping[str, Any]) -> list[dict[str, Any]]:
    """List-shaped trace for RiskDecision + graph ingest resolved_rules."""
    trace_id = evaluate.get("trace_id")
    decision = evaluate.get("decision")
    score = evaluate.get("score")
    header: dict[str, Any] = {
        "source": "decision_api",
        "action_map": ACTION_MAP_V1,
        "decision": decision,
        "rule_id": "decision_api_summary",
        "matched": True,
    }
    if trace_id is not None:
        header["trace_id"] = str(trace_id)
    if isinstance(score, (int, float)):
        header["policy_score"] = float(score)

    rows: list[dict[str, Any]] = [header]
    hits = evaluate.get("rule_hits")
    if isinstance(hits, list):
        for hit in hits:
            if isinstance(hit, str) and hit.strip():
                rows.append(
                    {
                        "rule_id": hit.strip(),
                        "matched": True,
                        "source": "decision_api",
                    },
                )
            elif isinstance(hit, dict):
                row = dict(hit)
                row.setdefault("source", "decision_api")
                row.setdefault("matched", True)
                rows.append(row)
    return rows


def wire_rule_data_from_evaluate(
    evaluate: Mapping[str, Any],
    *,
    transaction_id: str,
) -> dict[str, Any]:
    """Shape decision-api response into orchestrator rule_data (actions + RiskDecision fields)."""
    actions = map_evaluate_to_actions(evaluate)
    blocking = blocking_rule_id_from_evaluate(evaluate, actions)
    decision_raw = evaluate.get("decision")
    decision_out = str(decision_raw).strip().lower() if decision_raw is not None else ""
    # NATS review dispatch checks decision.upper() == "REVIEW"
    decision_wire = decision_out.upper() if decision_out else None

    scores: dict[str, float] = {}
    score = evaluate.get("score")
    if isinstance(score, (int, float)):
        scores["policy"] = float(score)
    ml = evaluate.get("ml_score")
    if isinstance(ml, (int, float)):
        scores["ml"] = float(ml)

    return {
        "transaction_id": transaction_id,
        "actions": actions,
        "blocking_rule_id": blocking,
        "evaluation_trace": evaluation_trace_from_evaluate(evaluate),
        "scores": scores,
        "decision": decision_wire,
        "decision_api": {
            "trace_id": str(evaluate.get("trace_id"))
            if evaluate.get("trace_id") is not None
            else None,
            "decision": decision_out,
            "tags": list(evaluate.get("tags") or [])
            if isinstance(evaluate.get("tags"), list)
            else [],
            "rule_hits": list(evaluate.get("rule_hits") or [])
            if isinstance(evaluate.get("rule_hits"), list)
            else [],
            "recommended_action": evaluate.get("recommended_action"),
            "action_map": ACTION_MAP_V1,
        },
    }


async def post_decision_evaluate(
    client: httpx.AsyncClient,
    *,
    decision_api_url: str,
    body: dict[str, Any],
    api_key: str | None = None,
) -> dict[str, Any]:
    """POST {DECISION_API_URL}/v1/decisions/evaluate → JSON dict.

    When ``api_key`` is set (or :envvar:`DECISION_API_KEY` /
    :envvar:`ORCHESTRATOR_DECISION_API_KEY` / first :envvar:`API_KEYS` entry),
    sends ``X-API-Key`` so evaluate works against auth-enabled decision-api.
    """
    base = decision_api_url.rstrip("/")
    url = f"{base}/v1/decisions/evaluate"
    headers = decision_api_auth_headers(api_key)
    response = await client.post(url, json=body, headers=headers or None)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise TypeError(f"decision-api evaluate returned non-object: {type(data).__name__}")
    return data


def decision_api_auth_headers(api_key: str | None = None) -> dict[str, str]:
    """Resolve service credentials for decision-api evaluate."""
    key = (api_key or "").strip()
    if not key:
        key = (
            os.environ.get("DECISION_API_KEY", "").strip()
            or os.environ.get("ORCHESTRATOR_DECISION_API_KEY", "").strip()
        )
    if not key:
        raw = os.environ.get("API_KEYS", "").strip()
        if raw:
            key = raw.split(",", 1)[0].strip()
    if not key:
        return {}
    return {"X-API-Key": key}


def _blocking_id(rule_data: Mapping[str, Any]) -> str | None:
    raw = rule_data.get("blocking_rule_id")
    if raw is None:
        return None
    if isinstance(raw, str):
        token = raw.strip()
        return token or None
    token = str(raw).strip()
    return token or None


def _actions_list(rule_data: Mapping[str, Any]) -> list[str]:
    raw = rule_data.get("actions")
    if not isinstance(raw, list):
        return []
    return [str(a) for a in raw]


def compare_rule_eval_outcomes(
    *,
    decision_api_rule_data: Mapping[str, Any],
    python_rule_data: Mapping[str, Any],
) -> dict[str, Any]:
    """Diff used by Phase 1 dual-run (actions + blocking_rule_id)."""
    da_actions = _actions_list(decision_api_rule_data)
    py_actions = _actions_list(python_rule_data)
    da_block = _blocking_id(decision_api_rule_data)
    py_block = _blocking_id(python_rule_data)
    return {
        "actions_match": da_actions == py_actions,
        "blocking_rule_id_match": da_block == py_block,
        "decision_api_actions": da_actions,
        "python_actions": py_actions,
        "decision_api_blocking_rule_id": da_block,
        "python_blocking_rule_id": py_block,
    }


def log_rule_eval_dual_run_diff(
    *,
    transaction_id: str,
    diff: Mapping[str, Any],
    python_error: str | None = None,
) -> None:
    """Structured dual-run log; WARNING on mismatch or secondary failure."""
    if python_error is not None:
        logger.warning(
            "orchestrator_rule_eval_dual_run transaction_id=%s python_error=%s "
            "side_effects=decision_api",
            transaction_id,
            python_error,
        )
        return
    match = bool(diff.get("actions_match")) and bool(diff.get("blocking_rule_id_match"))
    level = logging.INFO if match else logging.WARNING
    logger.log(
        level,
        "orchestrator_rule_eval_dual_run transaction_id=%s match=%s "
        "actions_match=%s blocking_rule_id_match=%s "
        "decision_api_actions=%s python_actions=%s "
        "decision_api_blocking_rule_id=%s python_blocking_rule_id=%s "
        "side_effects=decision_api",
        transaction_id,
        match,
        diff.get("actions_match"),
        diff.get("blocking_rule_id_match"),
        diff.get("decision_api_actions"),
        diff.get("python_actions"),
        diff.get("decision_api_blocking_rule_id"),
        diff.get("python_blocking_rule_id"),
    )
