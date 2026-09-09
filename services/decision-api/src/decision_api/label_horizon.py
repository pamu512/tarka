"""Tenant label-horizon windows. EXAMPLE defaults — not Tarka morals.

Readable config for later consume / join-rate glass. Not a chargeback-guarantee
SKU. Never auto-demote from these numbers.
"""

from __future__ import annotations

import json
import os
from typing import Any

from fastapi import HTTPException

from decision_api.gnn_loop.late_label import LABEL_KINDS, LateLabelError, normalize_label_kind
from decision_api.shared_path import ensure_services_shared_on_path

SCHEMA_ID = "tarka.label_horizon/v1"
ENV_JSON = "TARKA_LABEL_HORIZON_JSON"

# EXAMPLE tenant policy only. Buyers replace these. Not product morals.
EXAMPLE_HORIZONS_DAYS = {
    "fp": 7,
    "fraud": 90,
    "other": 30,
    "promo_abuse": 14,
    "collusion": 30,
    "chargeback": 90,
}


def require_known_label_kind(kind: str) -> str:
    try:
        return normalize_label_kind(kind)
    except LateLabelError as exc:
        raise HTTPException(
            status_code=422,
            detail={"reason_code": exc.code, "message": str(exc)},
        ) from exc


def _parse_kind_windows(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    inner = raw.get("by_kind") if isinstance(raw.get("by_kind"), dict) else raw
    if not isinstance(inner, dict):
        return {}
    out: dict[str, int] = {}
    for key, value in inner.items():
        kind = str(key or "").strip().lower()
        if kind not in LABEL_KINDS:
            continue
        days = value.get("window_days") if isinstance(value, dict) else value
        try:
            n = int(days)
        except (TypeError, ValueError):
            continue
        if n < 1 or n > 730:
            continue
        out[kind] = n
    return out


def _env_windows() -> dict[str, int]:
    blob = (os.environ.get(ENV_JSON) or "").strip()
    if not blob:
        return {}
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return {}
    return _parse_kind_windows(data)


def _provision_windows() -> dict[str, int]:
    ensure_services_shared_on_path()
    try:
        from desk_provision import load_desk_provision
    except ImportError:
        return {}
    return _parse_kind_windows(load_desk_provision().get("label_horizons"))


def _windows() -> dict[str, int]:
    out = dict(EXAMPLE_HORIZONS_DAYS)
    out.update(_provision_windows())
    out.update(_env_windows())
    return out


def horizon_policy() -> dict[str, Any]:
    """Full readable policy doc. Thresholds are tenant-owned examples."""
    by_kind = {
        kind: {"window_days": days, "example": True}
        for kind, days in _windows().items()
    }
    return {
        "schema_id": SCHEMA_ID,
        "example": True,
        "policy_owner": "tenant",
        "unit": "days",
        "by_kind": by_kind,
    }


def horizon_days(kind: str) -> int:
    token = require_known_label_kind(kind)
    return int(_windows()[token])
