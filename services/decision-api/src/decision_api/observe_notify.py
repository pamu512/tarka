"""Observe notify rows: desk inbox + optional outbound webhook.

Mutating ticks emit. GET shadow-promote-gate and evaluate must not call this.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query

from decision_api.shared_path import ensure_services_shared_on_path

ensure_services_shared_on_path()
from auth_rbac import require_role_or_insecure_desk  # noqa: E402

log = logging.getLogger("decision-api.observe_notify")

NOTIFY_SCHEMA = "tarka.observe_notify/v1"

EVENT_READY_TO_PROMOTE = "ready_to_promote"
EVENT_LIVE_RULE_SLIPPED = "live_rule_slipped"
EVENT_CONSIDER_DEMOTE = "consider_demote"
EVENT_CONSIDER_SUCCESSOR = "consider_successor"

_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def notify_path() -> Path:
    override = os.environ.get("TARKA_OBSERVE_NOTIFY_PATH", "").strip()
    if override:
        return Path(override)
    try:
        from decision_api.config import settings

        return Path(settings.rules_path) / "observe_notify.jsonl"
    except Exception:
        return Path("./rules") / "observe_notify.jsonl"


def english_copy(
    event_type: str, subject_id: str, draft_id: str = ""
) -> dict[str, str]:
    sid = (subject_id or "").strip() or "draft"
    href = f"/ops/shadow?draft={draft_id or sid}"
    if event_type == EVENT_READY_TO_PROMOTE:
        return {
            "title": "Ready to Promote",
            "body": f"Observe draft {sid} passed the desk gates. A human can Promote it. A model did not.",
            "href": href,
        }
    if event_type == EVENT_CONSIDER_DEMOTE:
        return {
            "title": "Consider taking this live rule back to Observe",
            "body": f"A retire draft is parked for live rule {sid}. The live rule is still on. A model did not turn it off.",
            "href": href,
        }
    if event_type == EVENT_CONSIDER_SUCCESSOR:
        return {
            "title": "Consider this successor in Observe",
            "body": f"A successor draft is parked for live rule {sid}. The live rule is still on. A model did not turn it off.",
            "href": href,
        }
    return {
        "title": "Live rule slipped",
        "body": f"Live rule {sid} slipped. The host did not park a draft. The rule is still live.",
        "href": href,
    }


def _load_rows() -> list[dict[str, Any]]:
    path = notify_path()
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
                if isinstance(row, dict) and row.get("id"):
                    out.append(row)
    except OSError:
        return []
    return out


def _write_rows(rows: Sequence[Mapping[str, Any]]) -> None:
    path = notify_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(dict(row), sort_keys=True, default=str) + "\n")


def list_notify(tenant_id: str) -> list[dict[str, Any]]:
    tid = (tenant_id or "").strip()
    if not tid:
        return []
    with _LOCK:
        rows = [r for r in _load_rows() if str(r.get("tenant_id") or "") == tid]
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows


def mark_read(tenant_id: str, notify_id: str) -> dict[str, Any]:
    tid = (tenant_id or "").strip()
    nid = (notify_id or "").strip()
    if not tid or not nid:
        return {}
    ts = _now()
    with _LOCK:
        rows = _load_rows()
        found: dict[str, Any] | None = None
        for row in rows:
            if (
                str(row.get("id") or "") == nid
                and str(row.get("tenant_id") or "") == tid
            ):
                if not row.get("read_at"):
                    row["read_at"] = ts
                found = dict(row)
                break
        if found is None:
            return {}
        _write_rows(rows)
        return found


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _post_webhook(payload: dict[str, Any], http: Any | None) -> str:
    url = os.environ.get("TARKA_OBSERVE_NOTIFY_WEBHOOK_URL", "").strip()
    if not url:
        return "skipped"
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    headers = {
        "content-type": "application/json",
        "x-tarka-observe-notify-event": str(payload.get("event") or ""),
    }
    secret = os.environ.get("TARKA_OBSERVE_NOTIFY_WEBHOOK_SECRET", "").strip()
    if secret:
        headers["x-tarka-signature"] = _sign(raw, secret)
    try:
        if http is not None:
            r = http.post(url, content=raw, headers=headers, timeout=5.0)
        else:
            import httpx

            r = httpx.post(url, content=raw, headers=headers, timeout=5.0)
        status = getattr(r, "status_code", None)
        if status is not None and 200 <= int(status) < 300:
            return "acked"
        return "non_2xx"
    except Exception:
        log.debug("observe_notify_webhook_failed", exc_info=True)
        return "failed"


def emit_observe_event(
    *,
    tenant_id: str,
    event_type: str,
    subject_id: str,
    draft_id: str = "",
    http: Any | None = None,
) -> dict[str, Any]:
    tid = (tenant_id or "").strip()
    kind = (event_type or "").strip()
    sid = (subject_id or "").strip()
    if not tid or not kind or not sid:
        return {"created": False, "webhook": "skipped"}
    copy = english_copy(kind, sid, draft_id)
    with _LOCK:
        rows = _load_rows()
        for row in rows:
            if (
                str(row.get("tenant_id") or "") == tid
                and str(row.get("type") or "") == kind
                and str(row.get("subject_id") or "") == sid
            ):
                return {"created": False, "webhook": "skipped", "id": row.get("id")}
        rec = {
            "id": str(uuid.uuid4()),
            "tenant_id": tid,
            "type": kind,
            "subject_id": sid,
            "title": copy["title"],
            "body": copy["body"],
            "href": copy["href"],
            "created_at": _now(),
            "read_at": None,
        }
        path = notify_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, sort_keys=True, default=str) + "\n")
    envelope = {
        "schema_id": NOTIFY_SCHEMA,
        "event": kind,
        "tenant_id": tid,
        "title": rec["title"],
        "body": rec["body"],
        "href": rec["href"],
        "subject_id": sid,
        "created_at": rec["created_at"],
    }
    webhook = _post_webhook(envelope, http)
    return {"created": True, "webhook": webhook, "id": rec["id"], "row": rec}


def maybe_emit_promote_ready(
    tenant_id: str,
    *,
    desk: Mapping[str, Any] | None,
    drafts: Sequence[Mapping[str, Any]] | None,
    http: Any | None = None,
) -> list[dict[str, Any]]:
    if not desk or not desk.get("promote_allowed"):
        return []
    created: list[dict[str, Any]] = []
    for draft in drafts or []:
        name = str(draft.get("name") or "").strip()
        if not name:
            continue
        out = emit_observe_event(
            tenant_id=tenant_id,
            event_type=EVENT_READY_TO_PROMOTE,
            subject_id=name,
            draft_id=name,
            http=http,
        )
        if out.get("created") and out.get("row"):
            created.append(out["row"])
    return created


def maybe_emit_slip_events(
    tenant_id: str,
    *,
    slip: Mapping[str, Any] | None,
    parked: Sequence[str] | None,
    http: Any | None = None,
) -> list[dict[str, Any]]:
    names = {str(x).strip() for x in (parked or []) if str(x).strip()}
    created: list[dict[str, Any]] = []
    for row in (slip or {}).get("rules") or []:
        if not isinstance(row, Mapping):
            continue
        rid = str(row.get("rule_id") or "").strip()
        if not rid:
            continue
        retire = f"slip_retire_{rid}"
        successor = f"slip_successor_{rid}"
        if retire in names:
            kind = EVENT_CONSIDER_DEMOTE
            draft = retire
        elif successor in names:
            kind = EVENT_CONSIDER_SUCCESSOR
            draft = successor
        elif row.get("parked_draft"):
            continue
        else:
            kind = EVENT_LIVE_RULE_SLIPPED
            draft = rid
        out = emit_observe_event(
            tenant_id=tenant_id,
            event_type=kind,
            subject_id=rid,
            draft_id=draft,
            http=http,
        )
        if out.get("created") and out.get("row"):
            created.append(out["row"])
    return created


def byom_status() -> dict[str, Any]:
    url = os.environ.get("SHADOW_LLM_BASE_URL", "").strip()
    backend = os.environ.get("SHADOW_LLM_BACKEND", "").strip()
    model = os.environ.get("SHADOW_LLM_MODEL", "").strip()
    connected = bool(url)
    return {
        "connected": connected,
        "backend": backend if connected else "off",
        "model": model if connected else "",
    }


def _safe_origin(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        return f"{parsed.scheme}://{host}" if host else ""
    except Exception:
        return ""


def byom_ping(http: Any | None = None) -> dict[str, Any]:
    status = byom_status()
    url = os.environ.get("SHADOW_LLM_BASE_URL", "").strip()
    if not url:
        return {**status, "ok": False, "hint": "llm_off"}
    probe = url.rstrip("/") + "/models"
    headers: dict[str, str] = {}
    key = os.environ.get("SHADOW_LLM_API_KEY", "").strip()
    if key:
        headers["authorization"] = f"Bearer {key}"
    try:
        if http is not None:
            r = http.get(probe, headers=headers, timeout=3.0)
        else:
            import httpx

            r = httpx.get(probe, headers=headers, timeout=3.0)
        code = getattr(r, "status_code", None)
        ok = code is not None and 200 <= int(code) < 300
        return {
            **status,
            "ok": ok,
            "hint": "ok" if ok else "ping_failed",
            "origin": _safe_origin(url),
        }
    except Exception:
        return {
            **status,
            "ok": False,
            "hint": "ping_failed",
            "origin": _safe_origin(url),
        }


async def emit_after_observe_tick(
    tenant_id: str,
    *,
    desk: Mapping[str, Any] | None = None,
    drafts: Sequence[Mapping[str, Any]] | None = None,
) -> None:
    """Called from mutating ticks only. Fail-soft. GET must not call this."""
    tid = (tenant_id or "").strip()
    if not tid:
        return
    try:
        if desk is None:
            from decision_api.db import SessionLocal
            from decision_api.leftover_promote_gate import (
                compute_desk_and_leftover_gates,
            )

            async with SessionLocal() as session:
                gates = await compute_desk_and_leftover_gates(
                    tid, None, session=session
                )
            desk = gates.get("desk_promote_gate")
        if drafts is None:
            from decision_api.json_rules import get_shadow_packs

            drafts = get_shadow_packs()
        maybe_emit_promote_ready(tid, desk=desk, drafts=drafts)
    except Exception:
        log.debug("observe_notify_tick_failed", exc_info=True)


router = APIRouter(tags=["observe-notify"])


@router.get("/v1/observe-notify")
def get_observe_notify(
    tenant_id: str = Query(..., min_length=1, max_length=128),
    _user=Depends(require_role_or_insecure_desk("analyst")),
) -> dict[str, Any]:
    rows = list_notify(tenant_id)
    unread = sum(1 for r in rows if not r.get("read_at"))
    return {"notifications": rows, "unread": unread}


@router.post("/v1/observe-notify/{notify_id}/read")
def post_observe_notify_read(
    notify_id: str,
    tenant_id: str = Query(..., min_length=1, max_length=128),
    _user=Depends(require_role_or_insecure_desk("analyst")),
) -> dict[str, Any]:
    row = mark_read(tenant_id, notify_id)
    if not row:
        raise HTTPException(404, "notify_not_found")
    return row


@router.get("/v1/ops/byom-status")
def get_byom_status(
    _user=Depends(require_role_or_insecure_desk("analyst")),
) -> dict[str, Any]:
    return byom_status()


@router.post("/v1/ops/byom-test")
def post_byom_test(
    _user=Depends(require_role_or_insecure_desk("analyst")),
) -> dict[str, Any]:
    return byom_ping()
