"""Outgoing marketplace Block webhook delivery logs (Prompt 175)."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

WebhookDeliveryStatus = Literal["pending", "delivered", "failed", "dlq"]

SIGNAL_BLOCK = "block"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _preview(payload: dict[str, Any], limit: int = 240) -> str:
    return json.dumps(payload, default=str)[:limit]


def _row_to_dict(row: Any, *, include_attempts: bool = False) -> dict[str, Any]:
    attempts = list(row.attempts_json or []) if include_attempts else []
    out: dict[str, Any] = {
        "id": str(row.id),
        "tenant_id": row.tenant_id,
        "signal": row.signal,
        "decision": row.decision,
        "entity_id": row.entity_id,
        "user_id": row.user_id,
        "trace_id": row.trace_id,
        "callback_url": row.callback_url,
        "status": row.status,
        "http_status": row.http_status,
        "attempt_count": int(row.attempt_count or 0),
        "latency_ms": row.latency_ms,
        "payload_preview": row.payload_preview,
        "last_error": row.last_error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None,
    }
    if include_attempts:
        out["attempts"] = attempts
        out["payload"] = row.payload_json if isinstance(row.payload_json, dict) else {}
    return out


async def record_marketplace_block_webhook(
    session: AsyncSession,
    *,
    tenant_id: str,
    callback_url: str,
    payload: dict[str, Any],
    entity_id: str | None = None,
    user_id: str | None = None,
    trace_id: str | None = None,
    decision: str = "BLOCK",
    blocking_rule_id: str | None = None,
) -> dict[str, Any]:
    """Persist a log row before/after delivery attempt."""
    from integration_ingress.models import MarketplaceWebhookLog

    tid = (tenant_id or "demo").strip() or "demo"
    body = dict(payload)
    body.setdefault("signal", SIGNAL_BLOCK)
    body.setdefault("decision", decision)
    body.setdefault("tenant_id", tid)
    if blocking_rule_id:
        body.setdefault("blocking_rule_id", blocking_rule_id)
    row = MarketplaceWebhookLog(
        id=uuid.uuid4(),
        tenant_id=tid,
        signal=SIGNAL_BLOCK,
        decision=str(body.get("decision") or decision),
        entity_id=str(entity_id or body.get("entity_id") or "")[:256] or None,
        user_id=str(user_id or body.get("user_id") or "")[:256] or None,
        trace_id=str(trace_id or body.get("trace_id") or "")[:128] or None,
        callback_url=callback_url.strip()[:2048],
        status="pending",
        payload_json=body,
        payload_preview=_preview(body),
        attempts_json=[],
        attempt_count=0,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _row_to_dict(row)


async def _append_attempt(
    row: Any,
    *,
    status_code: int | None,
    error: str | None,
    latency_ms: float | None,
) -> None:
    attempts = list(row.attempts_json or [])
    attempts.append(
        {
            "attempt": len(attempts) + 1,
            "status_code": status_code,
            "error": error,
            "latency_ms": latency_ms,
            "timestamp": _now_iso(),
        },
    )
    row.attempts_json = attempts
    row.attempt_count = len(attempts)
    if latency_ms is not None:
        row.latency_ms = round(latency_ms, 2)


async def deliver_marketplace_block_webhook(
    session: AsyncSession,
    http: httpx.AsyncClient,
    *,
    log_id: str,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """POST block payload to marketplace callback and update log row."""
    from integration_ingress.models import MarketplaceWebhookLog

    try:
        lid = uuid.UUID(str(log_id))
    except ValueError:
        raise LookupError("invalid log id") from None
    row = await session.scalar(select(MarketplaceWebhookLog).where(MarketplaceWebhookLog.id == lid))
    if row is None:
        raise LookupError("log not found")
    payload = row.payload_json if isinstance(row.payload_json, dict) else {}
    h = {
        "Content-Type": "application/json",
        "X-Tarka-Signal": SIGNAL_BLOCK,
        "X-Webhook-Id": str(row.id),
    }
    if headers:
        h.update(headers)
    t0 = datetime.now(UTC)
    try:
        r = await http.post(row.callback_url, json=payload, headers=h, timeout=timeout)
        latency = (datetime.now(UTC) - t0).total_seconds() * 1000.0
        await _append_attempt(row, status_code=r.status_code, error=None, latency_ms=latency)
        row.http_status = r.status_code
        if 200 <= r.status_code < 300:
            row.status = "delivered"
            row.delivered_at = datetime.now(UTC)
            row.last_error = None
        else:
            row.status = "failed"
            row.last_error = f"HTTP {r.status_code}"
    except Exception as exc:
        latency = (datetime.now(UTC) - t0).total_seconds() * 1000.0
        await _append_attempt(row, status_code=None, error=str(exc)[:500], latency_ms=latency)
        row.status = "failed"
        row.last_error = str(exc)[:500]
    await session.commit()
    await session.refresh(row)
    return _row_to_dict(row, include_attempts=True)


async def list_marketplace_webhook_logs(
    session: AsyncSession,
    *,
    tenant_id: str,
    status: str | None = None,
    signal: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    from integration_ingress.models import MarketplaceWebhookLog

    tid = (tenant_id or "demo").strip() or "demo"
    lim = max(1, min(int(limit), 500))
    q = (
        select(MarketplaceWebhookLog)
        .where(MarketplaceWebhookLog.tenant_id == tid)
        .order_by(MarketplaceWebhookLog.created_at.desc())
        .limit(lim)
    )
    if status:
        q = q.where(MarketplaceWebhookLog.status == status.strip().lower())
    if signal:
        q = q.where(MarketplaceWebhookLog.signal == signal.strip().lower())
    rows = (await session.scalars(q)).all()
    return [_row_to_dict(r) for r in rows]


async def get_marketplace_webhook_log(session: AsyncSession, *, log_id: str) -> dict[str, Any] | None:
    from integration_ingress.models import MarketplaceWebhookLog

    try:
        lid = uuid.UUID(str(log_id))
    except ValueError:
        return None
    row = await session.scalar(select(MarketplaceWebhookLog).where(MarketplaceWebhookLog.id == lid))
    if row is None:
        return None
    return _row_to_dict(row, include_attempts=True)
