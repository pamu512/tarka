"""Compatibility adapter: legacy rule_engine HTTP → decision-api (tarka_rule_engine).

Preserves documented ``POST /v1/evaluate`` response shape for one release when
``RULE_ENGINE_COMPAT_MODE=decision_api`` and ``DECISION_API_URL`` are set.

Removal gate: delete this module and the compat branch in ``main.py`` when
``RULE_EVAL_BACKEND=python`` / dual-run callers are gone
(rg -n 'RULE_EVAL_BACKEND=python|RULE_EVAL_DUAL_RUN|RULE_ENGINE_COMPAT_MODE').
"""

from __future__ import annotations

import logging
import os
from typing import Any, Mapping

import httpx

logger = logging.getLogger(__name__)

_COMPAT_MODE_ENV = "RULE_ENGINE_COMPAT_MODE"
_DECISION_API_URL_ENV = "DECISION_API_URL"


def compat_mode() -> str:
    """Return ``decision_api`` or ``local`` (default local AST for unit tests)."""
    raw = os.environ.get(_COMPAT_MODE_ENV, "").strip().lower()
    if raw in {"decision_api", "local"}:
        return raw
    return "local"


def decision_api_base_url() -> str | None:
    raw = os.environ.get(_DECISION_API_URL_ENV, "").strip().rstrip("/")
    return raw or None


def _decision_api_auth_headers() -> dict[str, str]:
    for key in ("DECISION_API_KEY", "ORCHESTRATOR_DECISION_API_KEY"):
        val = os.environ.get(key, "").strip()
        if val:
            return {"X-API-Key": val}
    raw_keys = os.environ.get("API_KEYS", "").strip()
    if raw_keys:
        first = raw_keys.split(",")[0].strip()
        if first:
            return {"X-API-Key": first}
    return {}


def _tenant_id_from_transaction(payload: Mapping[str, Any]) -> str:
    meta = payload.get("metadata")
    if isinstance(meta, dict):
        for key in ("tenant_id", "tenantId"):
            val = meta.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    for key in ("tenant_id", "tenantId"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return "default"


def map_tx_payload_to_evaluate_body(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Best-effort map of legacy ingest/transaction JSON → decision-api evaluate body."""
    entity_id = payload.get("entity_id") or payload.get("transaction_id") or "unknown"
    amount = payload.get("amount", 0)
    meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    features: dict[str, Any] = {"amount": amount}
    if isinstance(meta, dict):
        features.update({k: v for k, v in meta.items() if k not in {"tenant_id", "tenantId"}})
    return {
        "tenant_id": _tenant_id_from_transaction(payload),
        "event_type": str(payload.get("event_type") or meta.get("event_type") or "payment"),
        "entity_id": str(entity_id),
        "features": features,
        "device_context": payload.get("device_context")
        if isinstance(payload.get("device_context"), dict)
        else {},
    }


def map_evaluate_to_legacy_rule_response(
    evaluate: Mapping[str, Any],
    *,
    transaction_id: str,
) -> dict[str, Any]:
    """Map decision-api evaluate JSON → legacy ``{actions, transaction_id, ...}``."""
    decision = str(evaluate.get("decision") or "").strip().lower()
    if decision == "deny":
        actions = ["BLOCK"]
    elif decision == "review":
        actions = ["SHADOW_REVIEW", "FLAG"]
    elif decision == "allow":
        actions = ["ALLOW"]
    else:
        actions = ["FLAG"]

    recommended = evaluate.get("recommended_action")
    if isinstance(recommended, str):
        rec = recommended.strip().lower().replace(" ", "_")
        if rec.startswith("step_up") or rec.startswith("challenge") or rec in {
            "mfa",
            "step_up_mfa",
        }:
            if "FLAG" not in actions:
                actions.append("FLAG")

    tags = evaluate.get("tags")
    if isinstance(tags, list) and any(str(t).strip().lower() == "shadow_review" for t in tags):
        if "SHADOW_REVIEW" not in actions:
            actions.append("SHADOW_REVIEW")

    blocking: str | None = None
    if "BLOCK" in actions:
        hits = evaluate.get("rule_hits")
        if isinstance(hits, list):
            for hit in hits:
                if isinstance(hit, str) and hit.strip():
                    blocking = hit.strip()[:128]
                    break
                if isinstance(hit, dict):
                    rid = hit.get("rule_id") or hit.get("id")
                    if rid is not None and str(rid).strip():
                        blocking = str(rid).strip()[:128]
                        break
        if blocking is None:
            blocking = "decision_api_deny"

    return {
        "actions": actions,
        "transaction_id": transaction_id,
        "evaluation_trace": [
            {
                "source": "decision_api_compat",
                "decision": decision,
                "trace_id": evaluate.get("trace_id"),
                "matched": True,
            }
        ],
        "blocking_rule_id": blocking,
        "graph_context_fail_open": False,
        "compat": {"mode": "decision_api", "engine": "tarka_rule_engine"},
    }


async def evaluate_via_decision_api(payload: Mapping[str, Any]) -> dict[str, Any]:
    """POST decision-api evaluate and return legacy rule_engine response shape."""
    base = decision_api_base_url()
    if not base:
        raise RuntimeError(
            f"{_DECISION_API_URL_ENV} is required when {_COMPAT_MODE_ENV}=decision_api"
        )
    body = map_tx_payload_to_evaluate_body(payload)
    tid = str(payload.get("entity_id") or payload.get("transaction_id") or body["entity_id"])
    url = f"{base}/v1/decisions/evaluate"
    headers = _decision_api_auth_headers()
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=body, headers=headers or None)
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, dict):
        raise TypeError(f"decision-api evaluate returned non-object: {type(data).__name__}")
    logger.info(
        "rule_engine_compat_proxy decision=%s transaction_id=%s",
        data.get("decision"),
        tid,
    )
    return map_evaluate_to_legacy_rule_response(data, transaction_id=tid)


async def proxy_rules_reload_to_decision_api() -> dict[str, Any]:
    """Best-effort map of legacy ``POST /v1/rules/reload`` → decision-api admin reload."""
    base = decision_api_base_url()
    if not base:
        raise RuntimeError(
            f"{_DECISION_API_URL_ENV} is required when {_COMPAT_MODE_ENV}=decision_api"
        )
    url = f"{base}/v1/admin/rules/reload"
    headers = _decision_api_auth_headers()
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, headers=headers or None)
        response.raise_for_status()
        data = response.json() if response.content else {"ok": True}
    if not isinstance(data, dict):
        return {"ok": True, "compat": {"proxied": "decision_api_admin_reload"}}
    data.setdefault("compat", {"proxied": "decision_api_admin_reload"})
    return data
