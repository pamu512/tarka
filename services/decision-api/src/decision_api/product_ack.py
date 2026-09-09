"""Inbound product ACK + tenant-scoped delivery journal query.

Not Promote/Demote. Desk glass is G4.4. D9.3 GET /deliveries is not a case timeline.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

ACK_SCHEMA = "tarka.product_ack/v1"
ACK_LIST_SCHEMA = "tarka.product_ack_list/v1"
ACK_FIELDS = ("trace_id", "action_id", "status", "ts", "actor")
_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
_LOCK = threading.Lock()

router = APIRouter(prefix="/v1/enforcement", tags=["enforcement"])


class ProductAckError(Exception):
    def __init__(self, error: str, http_status: int, **extra: Any) -> None:
        super().__init__(error)
        self.error = error
        self.http_status = http_status
        self.extra = extra


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def product_ack_path() -> Path:
    override = os.environ.get("TARKA_PRODUCT_ACK_PATH", "").strip()
    if override:
        return Path(override)
    try:
        from decision_api.config import settings

        return Path(settings.rules_path) / "product_acks.jsonl"
    except Exception:
        return Path("./rules") / "product_acks.jsonl"


def _ack_secret() -> str:
    raw = os.environ.get("TARKA_ENFORCEMENT_WEBHOOK_SECRET")
    if raw is not None and raw.strip():
        return raw.strip()
    try:
        from desk_provision import hook_secret

        return hook_secret("enforcement")
    except Exception:
        return ""


def verify_tarka_signature(raw: bytes, secret: str, header_sig: str | None) -> bool:
    """Same brand as outbound enforcement: hex HMAC-SHA256 of the raw body."""
    if not secret:
        return True
    if not header_sig:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header_sig.strip())


def _journal_has_trace(trace_id: str, tenant_id: str) -> bool:
    # ponytail: O(n) journal scan; upgrade to audit PK / indexed store if this file grows.
    from decision_api.enforcement import enforcement_journal_path

    path = enforcement_journal_path()
    if not path.is_file():
        return False
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                if (
                    str(row.get("trace_id") or "") == trace_id
                    and str(row.get("tenant_id") or "") == tenant_id
                ):
                    return True
    except OSError:
        return False
    return False


def _audit_has_trace(trace_id: str, tenant_id: str) -> bool:
    """Best-effort decision_audit lookup. False when DATABASE_URL is unset."""
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        return False
    try:
        import uuid

        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session

        from decision_api.models import AuditRecord

        tid = uuid.UUID(trace_id)
    except Exception:
        return False
    sync = url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "sqlite+aiosqlite://", "sqlite://"
    )
    try:
        engine = create_engine(sync)
        with Session(engine) as session:
            row = session.execute(
                select(AuditRecord).where(AuditRecord.trace_id == tid)
            ).scalar_one_or_none()
            return bool(row and str(row.tenant_id) == tenant_id)
    except Exception:
        return False


def known_trace(trace_id: str, tenant_id: str) -> bool:
    tid = (trace_id or "").strip()
    ten = (tenant_id or "").strip()
    if not tid or not ten:
        return False
    if _journal_has_trace(tid, ten):
        return True
    return _audit_has_trace(tid, ten)


def _load_acks() -> list[dict[str, Any]]:
    path = product_ack_path()
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    out.append(row)
    except OSError:
        return []
    return out


def query_product_acks(
    *,
    trace_id: str,
    tenant_id: str,
    action_id: str | None = None,
) -> list[dict[str, Any]]:
    tid = (trace_id or "").strip()
    ten = (tenant_id or "").strip()
    aid = (action_id or "").strip()
    if not tid or not ten:
        return []
    with _LOCK:
        rows = _load_acks()
    out: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("trace_id") or "") != tid:
            continue
        if str(row.get("actor") or "") != ten:
            continue
        if aid and str(row.get("action_id") or "") != aid:
            continue
        out.append(row)
    return out


def accept_product_ack(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ProductAckError("malformed_ack", 400)
    action_id = str(payload.get("action_id") or "").strip()
    if not _HEX64.fullmatch(action_id):
        raise ProductAckError("malformed_action_id", 400, action_id=action_id)
    missing = [
        k
        for k in ACK_FIELDS
        if k != "action_id" and not str(payload.get(k) or "").strip()
    ]
    if missing:
        raise ProductAckError("malformed_ack", 400, fields=missing)
    trace_id = str(payload["trace_id"]).strip()
    actor = str(payload["actor"]).strip()
    if not known_trace(trace_id, actor):
        raise ProductAckError("unknown_trace", 404, trace_id=trace_id)
    record = {
        "schema_id": ACK_SCHEMA,
        "trace_id": trace_id,
        "action_id": action_id.lower(),
        "status": str(payload["status"]).strip(),
        "ts": str(payload["ts"]).strip() or _now(),
        "actor": actor,
    }
    path = product_ack_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True, default=str) + "\n"
    with _LOCK:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
    return record


def _http_error(exc: ProductAckError) -> HTTPException:
    return HTTPException(
        status_code=exc.http_status,
        detail={"error": exc.error, **exc.extra},
    )


@router.post("/acks")
async def post_product_ack(request: Request) -> dict[str, Any]:
    raw = await request.body()
    secret = _ack_secret()
    if secret:
        sig = request.headers.get("x-tarka-signature")
        if not verify_tarka_signature(raw, secret, sig):
            raise HTTPException(status_code=401, detail={"error": "bad_signature"})
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail={"error": "malformed_ack"}) from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail={"error": "malformed_ack"})
    try:
        return accept_product_ack(payload)
    except ProductAckError as exc:
        raise _http_error(exc) from exc


@router.get("/acks")
async def get_product_acks(
    trace_id: str = Query(..., min_length=1),
    tenant_id: str = Query(..., min_length=1),
    action_id: str | None = Query(default=None),
) -> dict[str, Any]:
    return {
        "schema_id": ACK_LIST_SCHEMA,
        "items": query_product_acks(
            trace_id=trace_id, tenant_id=tenant_id, action_id=action_id
        ),
    }


def _overlay_product_ack(row: dict[str, Any]) -> dict[str, Any]:
    """Product ACK is last_status=acked. Journal HTTP 2xx alone stays emitted."""
    acks = query_product_acks(
        trace_id=str(row.get("trace_id") or ""),
        tenant_id=str(row.get("tenant_id") or ""),
        action_id=str(row.get("action_id") or ""),
    )
    if not acks:
        return row
    row["last_status"] = "acked"
    ts = str(acks[-1].get("ts") or "").strip()
    if ts:
        row["acked_at"] = ts
    return row


@router.get("/deliveries")
async def get_enforcement_deliveries(
    trace_id: str = Query(..., min_length=1),
    tenant_id: str = Query(..., min_length=1),
    action_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> dict[str, Any]:
    from decision_api.enforcement import (
        DELIVERY_QUERY_SCHEMA,
        query_enforcement_deliveries,
    )

    rows = [
        _overlay_product_ack(row)
        for row in query_enforcement_deliveries(
            trace_id=trace_id, tenant_id=tenant_id, action_id=action_id
        )
    ]
    want = (status or "").strip().lower()
    if want:
        rows = [row for row in rows if row.get("last_status") == want]
    return {"schema_id": DELIVERY_QUERY_SCHEMA, "deliveries": rows}
