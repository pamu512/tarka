"""Tenant-scoped shadow auto-promote provision (file next to y_label_store).

Filenames are content-addressed (sha256 of the allowlisted tenant slug) so
filesystem paths never carry raw request tenant bytes.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from decision_api.y_label_store import _HEX64, _data_dir, _tenant_slug

SCHEMA = "tarka.shadow_auto_promote_provision/v1"

_lock = threading.Lock()


def _file_token(tenant_id: str) -> str:
    """Hex digest path segment — breaks CodeQL taint from request → path."""
    slug = _tenant_slug(tenant_id)
    digest = hashlib.sha256(f"tarka.shadow_auto_promote:{slug}".encode("utf-8")).hexdigest()
    if not _HEX64.fullmatch(digest):
        raise ValueError("invalid shadow auto-promote file token")
    return digest


def _path(tenant_id: str) -> Path:
    token = _file_token(tenant_id)
    base = _data_dir()
    target = (base / f"shadow_auto_promote_{token}.json").resolve()
    if target.parent != base or target.suffix != ".json":
        raise ValueError("provision path outside calibration data dir")
    return target


def default_provision(tenant_id: str) -> dict[str, Any]:
    return {
        "schema_id": SCHEMA,
        "tenant_id": tenant_id,
        "auto_promote": False,
        "leftover_add_cap": 10,
        "leftover_fp_rate_cap": 0.4,
        "min_labeled_extras": 5,
        "provisioned_by": "",
        "provisioned_at": "",
        "version": 0,
    }


def load_provision(tenant_id: str) -> dict[str, Any]:
    empty = default_provision(tenant_id)
    try:
        path = _path(tenant_id)
    except ValueError:
        return empty
    if not path.is_file():
        return empty
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty
    if not isinstance(raw, dict):
        return empty
    out = default_provision(tenant_id)
    out["auto_promote"] = bool(raw.get("auto_promote"))
    try:
        out["leftover_add_cap"] = int(raw.get("leftover_add_cap", 10))
    except (TypeError, ValueError):
        out["leftover_add_cap"] = 10
    try:
        out["leftover_fp_rate_cap"] = float(raw.get("leftover_fp_rate_cap", 0.4))
    except (TypeError, ValueError):
        out["leftover_fp_rate_cap"] = 0.4
    try:
        out["min_labeled_extras"] = int(raw.get("min_labeled_extras", 5))
    except (TypeError, ValueError):
        out["min_labeled_extras"] = 5
    try:
        out["version"] = int(raw.get("version", 0))
    except (TypeError, ValueError):
        out["version"] = 0
    out["provisioned_by"] = str(raw.get("provisioned_by") or "")
    out["provisioned_at"] = str(raw.get("provisioned_at") or "")
    if raw.get("schema_id"):
        out["schema_id"] = str(raw["schema_id"])
    return out


def _validate_caps(
    leftover_add_cap: int,
    leftover_fp_rate_cap: float,
    min_labeled_extras: int,
) -> None:
    if leftover_add_cap < 0:
        raise ValueError("leftover_add_cap must be >= 0")
    if leftover_fp_rate_cap < 0 or leftover_fp_rate_cap > 1:
        raise ValueError("leftover_fp_rate_cap must be in [0, 1]")
    if min_labeled_extras < 1:
        raise ValueError("min_labeled_extras must be >= 1")


def save_provision(
    tenant_id: str,
    *,
    auto_promote: bool,
    leftover_add_cap: int,
    leftover_fp_rate_cap: float,
    min_labeled_extras: int,
    provisioned_by: str,
) -> dict[str, Any]:
    _validate_caps(leftover_add_cap, leftover_fp_rate_cap, min_labeled_extras)
    now = datetime.now(timezone.utc).isoformat()
    with _lock:
        cur = load_provision(tenant_id)
        payload = {
            "schema_id": SCHEMA,
            "tenant_id": tenant_id,
            "auto_promote": bool(auto_promote),
            "leftover_add_cap": int(leftover_add_cap),
            "leftover_fp_rate_cap": float(leftover_fp_rate_cap),
            "min_labeled_extras": int(min_labeled_extras),
            "provisioned_by": str(provisioned_by or "")[:256],
            "provisioned_at": now,
            "version": int(cur.get("version") or 0) + 1,
        }
        path = _path(tenant_id)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return payload


def activate_shadow_pack(
    draft_id: str,
    *,
    actor: str,
    reason: str,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Flip the first shadow pack whose name matches draft_id to mode=active."""
    from decision_api.config import settings
    from decision_api.json_rules import get_shadow_packs, load_rules

    want = (draft_id or "").strip()
    match = next(
        (p for p in get_shadow_packs() if str(p.get("name") or "") == want),
        None,
    )
    if match is None:
        raise KeyError("no_shadow_draft")
    fname = str(match.get("_source_file") or match.get("_file") or "").strip()
    if not fname:
        raise KeyError("no_shadow_draft")
    fpath = Path(settings.rules_path) / fname
    pack = json.loads(fpath.read_text(encoding="utf-8"))
    pack["mode"] = "active"
    fpath.write_text(json.dumps(pack, indent=2), encoding="utf-8")
    load_rules()
    rec = {"draft_id": want, "mode": "active"}
    if detail:
        rec.update(detail)
    from decision_api.rule_api import _append_rule_change

    _append_rule_change(reason, fname, actor=actor, detail=rec)
    return {"promoted": True, "draft_id": want, "file": fname, "mode": "active"}


async def maybe_auto_promote_shadow(tenant_id: str) -> dict[str, Any]:
    """Host tick: activate AI-authored shadow packs when provisioned and gates green."""
    tid = (tenant_id or "").strip()
    provision = load_provision(tid)
    if not provision.get("auto_promote"):
        return {
            "auto_promote": False,
            "promoted": [],
            "reason": "not_provisioned",
        }
    from decision_api.db import SessionLocal
    from decision_api.leftover_promote_gate import compute_desk_and_leftover_gates

    async with SessionLocal() as session:
        gates = await compute_desk_and_leftover_gates(tid, None, session=session)
    leftover_g = gates["leftover_promote_gate"]
    desk = gates["desk_promote_gate"]
    leftover_blockers = [str(b) for b in (leftover_g.get("blockers") or [])]
    desk_blockers = [str(b) for b in (desk.get("blockers") or [])]
    blocked = bool(
        leftover_blockers
        or desk_blockers
        or not desk.get("promote_allowed")
        or "leftover_claimer_ack_required" in leftover_blockers
    )
    if blocked:
        reason = "promote_blocked"
        if "leftover_claimer_ack_required" in leftover_blockers:
            reason = "leftover_claimer_ack_required"
        elif leftover_blockers:
            reason = leftover_blockers[0]
        elif desk_blockers:
            reason = desk_blockers[0]
        return {
            "auto_promote": True,
            "promoted": [],
            "reason": reason,
            "leftover_promote_gate": leftover_g,
            "desk_promote_gate": desk,
        }
    from decision_api.json_rules import get_shadow_packs

    names = [
        str(p.get("name") or "")
        for p in get_shadow_packs()
        if p.get("is_ai_authored") and str(p.get("name") or "").strip()
    ]
    promoted: list[str] = []
    for name in names:
        activate_shadow_pack(
            name,
            actor="auto_promote",
            reason="auto_promote_shadow_pack",
            detail={"provision_version": provision.get("version")},
        )
        promoted.append(name)
    return {
        "auto_promote": True,
        "promoted": promoted,
        "reason": None,
        "leftover_promote_gate": leftover_g,
        "desk_promote_gate": desk,
    }
