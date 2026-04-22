from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from decision_api.config import settings

"""Stretch: load trusted geo zones from disk (per-tenant) for inference trusted_zone_hit."""

def _base_dir() -> Path:
    raw = os.environ.get("CALIBRATION_DATA_DIR", "").strip()
    if raw:
        p = Path(raw)
    else:
        p = Path(settings.rules_path) / "calibration_data"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_filename_segment(raw: str, *, max_len: int = 120) -> str:
    s = "".join(c if c.isalnum() or c in "._-" else "_" for c in (raw or "").strip())
    s = s[:max_len] if s else "default"
    return s


def load_trusted_zones_for_tenant(tenant_id: str) -> list[dict[str, Any]]:
    """Load zones from ``trusted_zones_<tenant>.json`` or ``trusted_zones_default.json``."""
    base = _base_dir()
    safe_tenant = _safe_filename_segment(tenant_id)
    tenant_path: Path | None = None
    wanted_name = f"trusted_zones_{safe_tenant}.json"
    for candidate in sorted(base.glob("trusted_zones_*.json")):
        if candidate.is_file() and candidate.name == wanted_name:
            tenant_path = candidate
            break
    for path in (tenant_path, base / "trusted_zones_default.json"):
        if path is None:
            continue
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, list):
            return [z for z in data if isinstance(z, dict)]
        if isinstance(data, dict) and isinstance(data.get("zones"), list):
            return [z for z in data["zones"] if isinstance(z, dict)]
    return []
