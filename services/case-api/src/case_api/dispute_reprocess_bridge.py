"""Dispute external reprocess → decision-api evaluate (fail-soft)."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

_EVALUATE_PATH = "/v1/decisions/evaluate"
_DELIVERY_HASH_KEYS = (
    "delivery_confirmation_hash",
    "pod_hash",
    "proof_of_delivery_hash",
    "expected_delivery_hash",
    "expected_delivery_confirmation_hash",
)
_DISPUTE_HOURS_KEYS = ("dispute_hours_since_delivery",)
_FRIENDLY_FRAUD_TAGS = frozenset({"risk:refund_burst"})


def _norm_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _resolve_event_type(dispute_type: str | None) -> str:
    dt = str(dispute_type or "").strip().lower()
    if dt in ("chargeback", "dispute"):
        return dt
    return "custom"


def _extract_nested_metadata(source: dict[str, Any] | None) -> dict[str, Any]:
    src = _norm_dict(source)
    for key in ("metadata", "payload"):
        nested = _norm_dict(src.get(key))
        if nested:
            return nested
    snap = _norm_dict(src.get("payload_snapshot"))
    for key in ("metadata", "payload", "request"):
        nested = _norm_dict(snap.get(key))
        if nested:
            return nested
    return {}


def _copy_delivery_fields(*sources: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for src in sources:
        meta = _extract_nested_metadata(src)
        for key in _DELIVERY_HASH_KEYS:
            val = meta.get(key)
            if isinstance(val, str) and val.strip() and key not in out:
                out[key] = val.strip()
        for key in _DISPUTE_HOURS_KEYS:
            if key in meta and key not in out:
                out[key] = meta[key]
    return out


def build_dispute_evaluate_body(
    dispute_row: Any,
    *,
    reason: str | None,
    original_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build POST /v1/decisions/evaluate body for dispute reprocess."""
    metadata: dict[str, Any] = {
        "checkpoint": "dispute",
        "decision_source": "dispute",
        "dispute_id": str(dispute_row.id),
        "reason_code": str(getattr(dispute_row, "reason_code", "") or ""),
        "dispute_type": str(getattr(dispute_row, "dispute_type", "") or ""),
        "trace_id": str(getattr(dispute_row, "trace_id", "") or ""),
    }
    reason_text = str(reason or "").strip()
    if reason_text:
        metadata["reprocess_reason"] = reason_text[:2000]

    metadata.update(_copy_delivery_fields(original_audit))

    event_type = _resolve_event_type(getattr(dispute_row, "dispute_type", None))
    body: dict[str, Any] = {
        "tenant_id": str(dispute_row.tenant_id),
        "entity_id": str(dispute_row.entity_id),
        "event_type": "custom",
        "metadata": metadata,
        "payload": {
            "amount": float(getattr(dispute_row, "amount", 0.0) or 0.0),
            "currency": str(getattr(dispute_row, "currency", "USD") or "USD"),
        },
    }
    if event_type in ("chargeback", "dispute"):
        body["metadata"]["event_subtype"] = event_type
    return body


def _infer_friendly_fraud_risk(data: dict[str, Any], tags: list[str]) -> bool | None:
    if any(t in _FRIENDLY_FRAUD_TAGS for t in tags):
        return True
    inf = data.get("inference_context")
    if isinstance(inf, dict):
        top = inf.get("top_signals")
        if isinstance(top, list) and any("friendly" in str(s).lower() for s in top):
            return True
    for hit in data.get("rule_hits") or []:
        if "friendly_fraud" in str(hit).lower() or "refund_burst" in str(hit).lower():
            return True
    return None


def _map_evaluate_response(data: dict[str, Any]) -> dict[str, Any]:
    tags = [str(t) for t in (data.get("tags") or []) if t is not None]
    out: dict[str, Any] = {
        "ok": True,
        "decision": data.get("decision"),
        "score": data.get("score"),
        "tags": tags,
    }
    ff = _infer_friendly_fraud_risk(data, tags)
    if ff is not None:
        out["is_friendly_fraud_risk"] = ff
    status = str(data.get("decision_status") or "").strip()
    if status.lower() == "degraded" or data.get("fallback_reason"):
        out["degraded"] = True
    return out


async def _fetch_original_audit(
    http: Any,
    *,
    decision_api_url: str,
    api_key: str,
    trace_id: str,
    tenant_id: str,
) -> dict[str, Any]:
    base = (decision_api_url or "").strip().rstrip("/")
    trace = str(trace_id or "").strip()
    if not base or not trace:
        return {}
    headers: dict[str, str] = {}
    key = (api_key or "").strip()
    if key:
        headers["x-api-key"] = key
    try:
        r = await http.get(
            f"{base}/v1/audit/{trace}",
            params={"tenant_id": tenant_id},
            headers=headers,
            timeout=5.0,
        )
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, dict) else {}
    except Exception as exc:
        log.warning("dispute_reprocess audit fetch failed trace=%s: %s", trace, exc)
    return {}


async def run_dispute_reprocess_evaluate(
    http: Any,
    *,
    decision_api_url: str,
    api_key: str,
    dispute_row: Any,
    reason: str | None,
    original_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST decision-api evaluate for dispute context; never raises."""
    base = (decision_api_url or "").strip().rstrip("/")
    if not base:
        return {"ok": False, "degraded": True, "error": "decision_api_url_unset"}

    audit = original_audit
    if audit is None:
        audit = await _fetch_original_audit(
            http,
            decision_api_url=base,
            api_key=api_key,
            trace_id=str(getattr(dispute_row, "trace_id", "") or ""),
            tenant_id=str(dispute_row.tenant_id),
        )

    body = build_dispute_evaluate_body(dispute_row, reason=reason, original_audit=audit)
    headers: dict[str, str] = {"Content-Type": "application/json"}
    key = (api_key or "").strip()
    if key:
        headers["x-api-key"] = key

    try:
        r = await http.post(
            f"{base}{_EVALUATE_PATH}",
            json=body,
            headers=headers,
            timeout=10.0,
        )
        if r.status_code >= 400:
            return {
                "ok": False,
                "degraded": True,
                "error": f"evaluate_http_{r.status_code}",
            }
        data = r.json()
        if not isinstance(data, dict):
            return {"ok": False, "degraded": True, "error": "evaluate_invalid_response"}
        return _map_evaluate_response(data)
    except Exception as exc:
        log.warning(
            "dispute_reprocess evaluate failed dispute=%s: %s",
            getattr(dispute_row, "id", "?"),
            exc,
        )
        return {"ok": False, "degraded": True, "error": str(exc)}
