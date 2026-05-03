"""Tenant-aware feature flags with percentage rollout support."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any


def _normalize_name(name: str) -> str:
    return str(name).strip().lower()


def _cohort_percentage(feature: str, tenant_id: str) -> int:
    digest = hashlib.sha256(f"{feature}:{tenant_id}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100


def _parse_bool(value: str) -> bool | None:
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "on", "enabled"}:
        return True
    if lowered in {"0", "false", "no", "off", "disabled"}:
        return False
    return None


def _to_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(100, parsed))


def _normalize_tenants(raw: Any) -> set[str]:
    if not isinstance(raw, list):
        return set()
    out: set[str] = set()
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.add(item.strip())
    return out


def _feature_flags_json() -> dict[str, Any]:
    raw = (os.environ.get("FEATURE_FLAGS_JSON") or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _env_key_for_flag(name: str) -> str:
    safe = _normalize_name(name).replace("-", "_").replace(".", "_")
    return f"FEATURE_FLAG_{safe.upper()}"


def is_feature_enabled(flag_name: str, *, tenant_id: str | None = None, default: bool = False) -> bool:
    """Return whether a feature is enabled for the given tenant context.

    Supports both:
    - `FEATURE_FLAG_<NAME>` override env (bool or rollout integer)
    - `FEATURE_FLAGS_JSON` map entries:
      - boolean value, or
      - object with keys: enabled, rollout_pct, rollout_percentage, tenants, allow_tenants, deny_tenants
    """
    name = _normalize_name(flag_name)
    env_override = (os.environ.get(_env_key_for_flag(name)) or "").strip()
    if env_override:
        as_bool = _parse_bool(env_override)
        if as_bool is not None:
            return as_bool
        rollout = _to_int(env_override, default=-1)
        if rollout >= 0:
            if rollout >= 100:
                return True
            if rollout <= 0:
                return False
            if not tenant_id:
                return False
            return _cohort_percentage(name, tenant_id) < rollout
        return default

    flags = _feature_flags_json()
    cfg = flags.get(name)
    if cfg is None:
        return default
    if isinstance(cfg, bool):
        return cfg
    if not isinstance(cfg, dict):
        return default

    enabled = bool(cfg.get("enabled", default))
    if not enabled:
        return False

    deny_tenants = _normalize_tenants(cfg.get("deny_tenants"))
    if tenant_id and tenant_id in deny_tenants:
        return False

    allow_tenants = _normalize_tenants(cfg.get("tenants")) | _normalize_tenants(cfg.get("allow_tenants"))
    if tenant_id and tenant_id in allow_tenants:
        return True

    rollout_pct = _to_int(cfg.get("rollout_pct", cfg.get("rollout_percentage", 100)), default=100)
    if rollout_pct >= 100:
        return True
    if rollout_pct <= 0:
        return False
    if not tenant_id:
        return False
    return _cohort_percentage(name, tenant_id) < rollout_pct


def feature_enabled(feature: str, *, tenant_id: str | None = None, default: bool = False) -> bool:
    """Alias helper with concise name used by service code."""
    return is_feature_enabled(feature, tenant_id=tenant_id, default=default)

