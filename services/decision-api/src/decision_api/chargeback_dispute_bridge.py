"""Open case-api dispute from Ethoca/Verifi-class early-alert normalize output."""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Callable

import httpx

log = logging.getLogger("decision-api.chargeback_dispute_bridge")


def case_api_base() -> str:
    return (
        (os.environ.get("CASE_API_URL") or os.environ.get("TARKA_CASE_API_URL") or "")
        .strip()
        .rstrip("/")
    )


def should_open_dispute(normalized: dict[str, Any] | None) -> bool:
    if not isinstance(normalized, dict):
        return False
    feats = normalized.get("features")
    if not isinstance(feats, dict):
        return False
    if not feats.get("chargeback_early_alert"):
        return False
    # dispute_hint may be {} after normalize edge cases — alert flag is enough
    return True


def build_dispute_request(
    *,
    tenant_id: str,
    normalized: dict[str, Any],
    entity_id: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    feats = (
        normalized.get("features")
        if isinstance(normalized.get("features"), dict)
        else {}
    )
    hint = (
        normalized.get("dispute_hint")
        if isinstance(normalized.get("dispute_hint"), dict)
        else {}
    )
    txn = str(
        entity_id
        or feats.get("transaction_id")
        or hint.get("transaction_id")
        or "unknown"
    )[:256]
    alert_id = str(
        feats.get("chargeback_alert_id")
        or hint.get("alert_id")
        or uuid.uuid4().hex[:12]
    )
    tid = (trace_id or f"cb-alert:{alert_id}").strip()[:128]
    amount = 0.0
    try:
        amount = float(feats.get("amount") or 0.0)
    except (TypeError, ValueError):
        amount = 0.0
    return {
        "tenant_id": tenant_id,
        "entity_id": txn,
        "trace_id": tid,
        "dispute_type": "chargeback",
        "reason_code": str(
            feats.get("chargeback_reason_code") or hint.get("reason_code") or ""
        )[:64],
        "amount": amount,
        "currency": str(feats.get("currency") or "USD")[:8],
        "card_network": str(
            normalized.get("provider") or feats.get("chargeback_alert_provider") or ""
        )[:64]
        or None,
    }


async def maybe_open_dispute_from_alert(
    *,
    http: httpx.AsyncClient | None,
    tenant_id: str,
    normalized: dict[str, Any],
    entity_id: str | None = None,
    trace_id: str | None = None,
    api_key: str | None = None,
    metrics_inc: Callable[[str], None] | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Best-effort POST /v1/disputes — fail-soft (never raises to webhook caller)."""
    if not should_open_dispute(normalized):
        return {"opened": False, "skipped_reason": "no_alert"}
    base = case_api_base()
    if not base:
        return {"opened": False, "skipped_reason": "case_api_unconfigured"}
    if http is None:
        return {"opened": False, "skipped_reason": "http_client_missing"}
    body = build_dispute_request(
        tenant_id=tenant_id,
        normalized=normalized,
        entity_id=entity_id,
        trace_id=trace_id,
    )
    headers: dict[str, str] = {"Content-Type": "application/json"}
    key = (api_key or os.environ.get("API_KEYS", "").split(",")[0] or "").strip()
    if key:
        headers["x-api-key"] = key
    try:
        r = await http.post(
            f"{base}/v1/disputes",
            json=body,
            headers=headers,
            timeout=timeout_seconds,
        )
        if r.status_code >= 400:
            if metrics_inc:
                metrics_inc("chargeback_dispute_bridge_failed")
            return {
                "opened": False,
                "skipped_reason": f"upstream_http_{r.status_code}",
                "request": body,
            }
        data = r.json() if r.content else {}
        if metrics_inc:
            metrics_inc("chargeback_dispute_bridge_opened")
        dispute = data if isinstance(data, dict) else {"raw": data}
        dispute_id = (
            str(dispute.get("id") or dispute.get("dispute_id") or "").strip() or None
        )
        # Attach dispute id + evidence pack onto caller's dispute_hint (mutate)
        hint = normalized.get("dispute_hint")
        if isinstance(hint, dict) and dispute_id:
            hint["dispute_id"] = dispute_id
            from decision_api.chargeback_alert_webhook import (
                build_evaluate_reprocess_metadata,
            )

            feats = (
                normalized.get("features")
                if isinstance(normalized.get("features"), dict)
                else {}
            )
            hint["evaluate_reprocess"] = build_evaluate_reprocess_metadata(
                dispute_hint=hint, features=feats
            )
        return {
            "opened": True,
            "dispute": dispute,
            "dispute_id": dispute_id,
            "request": body,
            "live_claim_allowed": False,
        }
    except Exception:
        log.exception("chargeback_dispute_bridge_failed")
        if metrics_inc:
            metrics_inc("chargeback_dispute_bridge_failed")
        return {
            "opened": False,
            "skipped_reason": "upstream_error",
            "request": body,
        }
