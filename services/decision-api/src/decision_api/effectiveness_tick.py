"""Effectiveness tick: numbered Suggest Propose Demote. Never demotes."""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from decision_api.loop_metrics import compute_pack_metrics
from decision_api.y_label_store import _HEX64, _data_dir, _tenant_slug

SCHEMA_ID = "tarka.effectiveness_suggestion/v1"
# EXAMPLE tenant policy — not Tarka morals. Desk Confirm still required.
DIVERGENCE_SUGGEST = 0.5

_lock = threading.Lock()


def _file_token(tenant_id: str) -> str:
    slug = _tenant_slug(tenant_id)
    digest = hashlib.sha256(
        f"tarka.effectiveness_suggestions:{slug}".encode("utf-8")
    ).hexdigest()
    if not _HEX64.fullmatch(digest):
        raise ValueError("invalid effectiveness suggestion file token")
    return digest


def _path(tenant_id: str) -> Path:
    token = _file_token(tenant_id)
    base = _data_dir()
    target = (base / f"effectiveness_suggestions_{token}.json").resolve()
    if target.parent != base or target.suffix != ".json":
        raise ValueError("suggestion path outside calibration data dir")
    return target


def _pack_id(pack: dict[str, Any]) -> str:
    return str(pack.get("name") or pack.get("pack_id") or "").strip()


def _is_active(pack: dict[str, Any]) -> bool:
    return str(pack.get("mode") or "active") in {"active", ""}


def _fp_count(
    pack_id: str,
    observations: list[dict[str, Any]],
    labels: dict[str, Any],
    tenant_id: str,
) -> int:
    kinds = labels.get("label_kind_by_trace") if isinstance(labels, dict) else {}
    kinds = kinds if isinstance(kinds, dict) else {}
    n = 0
    for row in observations:
        if not isinstance(row, dict):
            continue
        row_tenant = str(row.get("tenant_id") or "").strip()
        if row_tenant and row_tenant != tenant_id:
            continue
        if str(row.get("pack_id") or "").strip() != pack_id:
            continue
        tid = str(row.get("trace_id") or "").strip()
        if tid and str(kinds.get(tid) or "").strip().lower() == "fp":
            n += 1
    return n


def _reason_code(*, divergence: float | None, fp_count: int) -> str | None:
    high_div = divergence is not None and divergence >= DIVERGENCE_SUGGEST
    if high_div and fp_count > 0:
        return "high_divergence_and_fp"
    if high_div:
        return "high_shadow_divergence"
    if fp_count > 0:
        return "fp_labeled"
    return None


def run_effectiveness_tick(
    packs: list[dict[str, Any]],
    observations: list[dict[str, Any]] | None,
    labels: dict[str, Any] | None,
    *,
    tenant_id: str,
    persist: bool = False,
) -> dict[str, Any]:
    """Score Active packs. Emit suggestions only — no pack writes."""
    want = (tenant_id or "").strip()
    rows = observations if isinstance(observations, list) else []
    label_blob = labels if isinstance(labels, dict) else {}
    if not want:
        return {"suggestions": [], "persisted": False}
    metrics = {
        str(r.get("pack_id") or ""): r
        for r in compute_pack_metrics(packs, rows, tenant_id=want)
        if isinstance(r, dict)
    }
    suggestions: list[dict[str, Any]] = []
    as_of = datetime.now(timezone.utc).isoformat()
    seen: set[str] = set()
    for pack in packs:
        if not isinstance(pack, dict) or not _is_active(pack):
            continue
        pack_tenant = str(pack.get("tenant_id") or "").strip()
        if pack_tenant and pack_tenant != want:
            continue
        pid = _pack_id(pack)
        if not pid or pid in seen:
            continue
        seen.add(pid)
        row = metrics.get(pid) or {}
        hit = row.get("rule_hit_rate")
        div = row.get("shadow_divergence")
        fp_n = _fp_count(pid, rows, label_blob, want)
        reason = _reason_code(divergence=div, fp_count=fp_n)
        if not reason:
            continue
        suggestions.append(
            {
                "schema_id": SCHEMA_ID,
                "pack_id": pid,
                "tenant_id": want,
                "rule_hit_rate": hit,
                "shadow_divergence": div,
                "fp_count": fp_n,
                "reason_code": reason,
                "action": "suggest_propose_demote",
                "window": row.get("window") or "7d",
                "as_of": as_of,
            }
        )
    persisted = False
    if persist:
        _write_suggestions(want, suggestions)
        persisted = True
    return {"suggestions": suggestions, "persisted": persisted}


def _write_suggestions(tenant_id: str, items: list[dict[str, Any]]) -> None:
    path = _path(tenant_id)
    blob = {
        "schema_id": SCHEMA_ID,
        "tenant_id": tenant_id,
        "suggestions": items,
    }
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(blob), encoding="utf-8")


def load_suggestions(tenant_id: str) -> list[dict[str, Any]]:
    want = (tenant_id or "").strip()
    if not want:
        return []
    try:
        path = _path(want)
    except ValueError:
        return []
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, dict):
        return []
    items = raw.get("suggestions")
    return items if isinstance(items, list) else []
