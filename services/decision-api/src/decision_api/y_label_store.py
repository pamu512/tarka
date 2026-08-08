"""File-backed disposition y_label store (critical regrade flag #1).

Persists trace/entity → 0/1 labels under the calibration data dir so GET
reliability-bins can join without re-POSTing the map every time.
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_SAFE_TENANT = re.compile(r"^[A-Za-z0-9._-]{1,120}$")


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


def _path(tenant_id: str) -> Path:
    base = _data_dir()
    name = f"y_labels_{_tenant_slug(tenant_id)}.json"
    # Construct from basename only so path cannot escape base.
    target = (base / Path(name).name).resolve()
    if not target.is_relative_to(base) or target.parent != base:
        raise ValueError("y_label path outside calibration data dir")
    return target


def load_y_labels(tenant_id: str) -> dict[str, dict[str, str]]:
    try:
        path = _path(tenant_id)
    except ValueError:
        return {"by_trace": {}, "by_entity": {}}
    if not path.is_file():
        return {"by_trace": {}, "by_entity": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))  # codeql[py/path-injection]
    except (OSError, json.JSONDecodeError):
        return {"by_trace": {}, "by_entity": {}}
    if not isinstance(raw, dict):
        return {"by_trace": {}, "by_entity": {}}
    by_t = raw.get("by_trace") if isinstance(raw.get("by_trace"), dict) else {}
    by_e = raw.get("by_entity") if isinstance(raw.get("by_entity"), dict) else {}
    return {
        "by_trace": {str(k): str(v) for k, v in by_t.items() if str(v) in {"0", "1"}},
        "by_entity": {str(k): str(v) for k, v in by_e.items() if str(v) in {"0", "1"}},
    }


def merge_y_labels(
    tenant_id: str,
    *,
    by_trace: dict[str, str] | None = None,
    by_entity: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Merge 0/1 maps into durable store. Returns store snapshot + counts."""
    with _lock:
        cur = load_y_labels(tenant_id)
        t_map = dict(cur["by_trace"])
        e_map = dict(cur["by_entity"])
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
        payload = {"by_trace": t_map, "by_entity": e_map}
        path = _path(tenant_id)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )  # codeql[py/path-injection]
        return {
            "tenant_id": tenant_id,
            "trace_labels": len(t_map),
            "entity_labels": len(e_map),
            "updated": added,
            "by_trace": t_map,
            "by_entity": e_map,
        }
