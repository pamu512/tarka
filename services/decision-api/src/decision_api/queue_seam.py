"""Outbound leftover/FLAG → buyer queue. Empty QUEUE_WEBHOOK_URL = off. Not a CRM."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

log = logging.getLogger("decision-api.queue_seam")

QUEUE_UPSERT_SCHEMA = "tarka.queue_upsert/v1"
_STATUS_LOCK = threading.Lock()
_LAST_STATUS: dict[str, Any] = {
    "connected": False,
    "last_ok_at": None,
    "last_error_at": None,
    "last_error": None,
}


def queue_webhook_url() -> str:
    raw = os.environ.get("QUEUE_WEBHOOK_URL")
    if raw is not None:
        return raw.strip()
    try:
        from desk_provision import hook_url

        return hook_url("queue")
    except Exception:
        return ""


def queue_webhook_secret() -> str:
    raw = os.environ.get("QUEUE_WEBHOOK_SECRET")
    if raw is not None and raw.strip():
        return raw.strip()
    try:
        from desk_provision import hook_secret

        return hook_secret("queue")
    except Exception:
        return ""


def queue_seam_mode() -> str:
    token = (os.environ.get("QUEUE_SEAM_MODE") or "webhook").strip().lower()
    return token if token in {"webhook", "issue_tracker"} else "webhook"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _desk_deep_link(*, leftover_id: str, trace_id: str) -> str:
    base = (os.environ.get("DESK_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if not base:
        return ""
    q = f"leftover_id={quote(leftover_id)}&trace_id={quote(trace_id)}"
    return f"{base}/leftovers?{q}"


def build_queue_upsert(
    *,
    tenant_id: str,
    leftover_id: str,
    trace_id: str,
    entity_id: str,
    action: str,
    pack_why_summary: str = "",
    evaluation_token: str = "",
    flag_id: str = "",
    enforcement_mode: str = "emit_only",
) -> dict[str, Any]:
    why = (pack_why_summary or "").strip()[:240]
    lid = (leftover_id or flag_id or trace_id or "").strip()
    return {
        "schema_id": QUEUE_UPSERT_SCHEMA,
        "tenant_id": tenant_id,
        "leftover_id": lid,
        "flag_id": (flag_id or "").strip() or None,
        "trace_id": trace_id,
        "evaluation_token": (evaluation_token or trace_id or "").strip(),
        "entity_id": entity_id,
        "action": action,
        "enforcement_mode": enforcement_mode,
        "pack_why_summary": why,
        "deep_link": _desk_deep_link(leftover_id=lid, trace_id=trace_id),
        "emitted_at": _now(),
    }


def last_queue_status() -> dict[str, Any]:
    with _STATUS_LOCK:
        return {
            "connected": bool(queue_webhook_url()),
            **{k: v for k, v in _LAST_STATUS.items() if k != "connected"},
            "mode": queue_seam_mode(),
        }


def _record_status(*, ok: bool, error: str = "") -> None:
    ts = _now()
    with _STATUS_LOCK:
        _LAST_STATUS["connected"] = bool(queue_webhook_url())
        if ok:
            _LAST_STATUS["last_ok_at"] = ts
            _LAST_STATUS["last_error"] = None
        else:
            _LAST_STATUS["last_error_at"] = ts
            _LAST_STATUS["last_error"] = (error or "error")[:200]


def _issue_tracker_payload(body: dict[str, Any]) -> dict[str, Any]:
    title = f"Tarka leftover {body.get('leftover_id') or body.get('trace_id')}"
    desc = (
        f"entity={body.get('entity_id')} action={body.get('action')} "
        f"why={body.get('pack_why_summary')} link={body.get('deep_link')}"
    )
    return {"title": title, "body": desc, "queue_upsert": body}


async def emit_queue_upsert(
    *,
    http: Any,
    tenant_id: str,
    leftover_id: str,
    trace_id: str,
    entity_id: str,
    action: str,
    pack_why_summary: str = "",
    evaluation_token: str = "",
    flag_id: str = "",
    enforcement_mode: str = "emit_only",
) -> dict[str, Any]:
    """POST queue.upsert. Empty URL = no-op. Never raises into evaluate/mint."""
    url = queue_webhook_url()
    payload = build_queue_upsert(
        tenant_id=tenant_id,
        leftover_id=leftover_id,
        trace_id=trace_id,
        entity_id=entity_id,
        action=action,
        pack_why_summary=pack_why_summary,
        evaluation_token=evaluation_token,
        flag_id=flag_id,
        enforcement_mode=enforcement_mode,
    )
    if not url:
        return {"dispatched": False, "reason": "url_unset"}
    body = (
        _issue_tracker_payload(payload)
        if queue_seam_mode() == "issue_tracker"
        else payload
    )
    raw = json.dumps(body, sort_keys=True, default=str).encode("utf-8")
    headers = {
        "content-type": "application/json",
        "x-tarka-queue-event": "queue.upsert",
    }
    secret = queue_webhook_secret()
    if secret:
        headers["x-tarka-signature"] = _sign(raw, secret)
    tracker_auth = (os.environ.get("ISSUE_TRACKER_AUTH_HEADER") or "").strip()
    if tracker_auth and queue_seam_mode() == "issue_tracker":
        headers["authorization"] = tracker_auth
    try:
        r = await http.post(url, content=raw, headers=headers, timeout=5.0)
        status = getattr(r, "status_code", None)
        ok = status is not None and 200 <= int(status) < 300
        if ok:
            _record_status(ok=True)
        else:
            _record_status(ok=False, error=f"http_{status}")
            log.warning("queue_upsert_non_2xx status=%s trace_id=%s", status, trace_id)
        return {"dispatched": True, "ok": ok, "status_code": status}
    except Exception as exc:
        _record_status(ok=False, error=str(exc)[:200])
        log.warning("queue_upsert_failed trace_id=%s: %s", trace_id, exc)
        return {"dispatched": True, "ok": False, "error": str(exc)[:200]}


def persist_queue_status(path: str | os.PathLike[str] | None = None) -> None:
    dest = Path(path or os.environ.get("QUEUE_SEAM_STATUS_PATH") or "")
    if not dest.name:
        return
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(last_queue_status()), encoding="utf-8")
    except OSError:
        log.debug("queue_status_persist_failed", exc_info=True)
