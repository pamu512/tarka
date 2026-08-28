"""File-backed disposition y_label store (critical regrade flag #1).

Persists trace/entity → 0/1 labels under the calibration data dir so GET
reliability-bins can join without re-POSTing the map every time.

Filenames are content-addressed (sha256 of the allowlisted tenant slug) so
filesystem paths never carry raw request tenant bytes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_SAFE_TENANT = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _data_dir() -> Path:
    from decision_api.config import settings

    base = os.environ.get("CALIBRATION_DATA_DIR", "").strip()
    if base:
        p = Path(base).resolve()
    else:
        p = (Path(settings.rules_path) / "calibration_data").resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _tenant_slug(tenant_id: str) -> str:
    """Allowlist tenant segment — no path separators or traversal tokens."""
    raw = (tenant_id or "").strip()
    if _SAFE_TENANT.fullmatch(raw) and raw not in {".", ".."}:
        return raw
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in raw)[:120]
    if not safe or safe in {".", ".."}:
        return "default"
    return safe


def _file_token(tenant_id: str) -> str:
    """Hex digest path segment — breaks CodeQL taint from request → path."""
    slug = _tenant_slug(tenant_id)
    digest = hashlib.sha256(f"tarka.y_labels:{slug}".encode("utf-8")).hexdigest()
    if not _HEX64.fullmatch(digest):
        raise ValueError("invalid y_label file token")
    return digest


def _path(tenant_id: str) -> Path:
    token = _file_token(tenant_id)
    base = _data_dir()
    # Constant prefix + hex-only token (no user string in the join).
    target = (base / f"y_labels_{token}.json").resolve()
    if target.parent != base or target.suffix != ".json":
        raise ValueError("y_label path outside calibration data dir")
    return target


def _read_raw(tenant_id: str) -> dict[str, Any]:
    try:
        path = _path(tenant_id)
    except ValueError:
        return {}
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def load_y_labels(tenant_id: str) -> dict[str, dict[str, str]]:
    raw = _read_raw(tenant_id)
    by_t = raw.get("by_trace") if isinstance(raw.get("by_trace"), dict) else {}
    by_e = raw.get("by_entity") if isinstance(raw.get("by_entity"), dict) else {}
    return {
        "by_trace": {str(k): str(v) for k, v in by_t.items() if str(v) in {"0", "1"}},
        "by_entity": {str(k): str(v) for k, v in by_e.items() if str(v) in {"0", "1"}},
    }


def load_override_whys(tenant_id: str) -> dict[str, str]:
    raw = _read_raw(tenant_id)
    why = raw.get("why_by_trace") if isinstance(raw.get("why_by_trace"), dict) else {}
    return {str(k): str(v).strip() for k, v in why.items() if str(v).strip()}


def merge_y_labels(
    tenant_id: str,
    *,
    by_trace: dict[str, str] | None = None,
    by_entity: dict[str, str] | None = None,
    why_by_trace: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Merge 0/1 maps into durable store. Returns store snapshot + counts."""
    with _lock:
        cur = load_y_labels(tenant_id)
        t_map = dict(cur["by_trace"])
        e_map = dict(cur["by_entity"])
        why_map = load_override_whys(tenant_id)
        added = 0
        for k, v in (by_trace or {}).items():
            key = str(k).strip()
            if key and v in {"0", "1"} and t_map.get(key) != v:
                t_map[key] = v
                added += 1
            elif key and v in {"0", "1"}:
                t_map[key] = v
        for k, v in (by_entity or {}).items():
            key = str(k).strip()
            if key and v in {"0", "1"}:
                e_map[key] = v
        for k, v in (why_by_trace or {}).items():
            key = str(k).strip()
            reason = str(v).strip()
            if key and reason:
                why_map[key] = reason
        payload = {"by_trace": t_map, "by_entity": e_map, "why_by_trace": why_map}
        path = _path(tenant_id)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return {
            "tenant_id": tenant_id,
            "trace_labels": len(t_map),
            "entity_labels": len(e_map),
            "updated": added,
            "by_trace": t_map,
            "by_entity": e_map,
            "why_by_trace": why_map,
        }
