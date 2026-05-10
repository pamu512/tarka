"""Compact recent-audit rows for live dashboards (GET /v1/audit/recent)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from decision_api.audit_recent_derive import derive_rule_result
from decision_api.models import AuditRecord


def _short_id(trace_id: UUID | str) -> str:
    s = str(trace_id).replace("-", "")
    return (s[:8] or "UNKNOWN").upper()


def _coerce_amount(payload: dict[str, Any]) -> tuple[float | None, str | None]:
    raw = payload.get("amount")
    if raw is None:
        return None, None
    try:
        amt = float(raw)
    except (TypeError, ValueError):
        return None, None
    cur = payload.get("currency")
    cur_s = (
        str(cur).strip().upper()[:8] if cur is not None and str(cur).strip() else None
    )
    return amt, cur_s


def _ai_confidence(snap: dict[str, Any]) -> float | None:
    inf = snap.get("inference_context")
    if not isinstance(inf, dict):
        return None
    v = inf.get("integrity_confidence")
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        x = float(v)
        if 0.0 <= x <= 1.0:
            return x
    return None


def shape_audit_recent_item(row: AuditRecord) -> dict[str, Any]:
    snap = row.payload_snapshot if isinstance(row.payload_snapshot, dict) else {}
    payload = snap.get("payload") if isinstance(snap.get("payload"), dict) else {}
    amount, currency = _coerce_amount(payload)
    return {
        "trace_id": str(row.trace_id),
        "short_id": _short_id(row.trace_id),
        "amount": amount,
        "currency": currency,
        "rule_result": derive_rule_result(row.decision, row.tags, snap),
        "ai_confidence": _ai_confidence(snap),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
