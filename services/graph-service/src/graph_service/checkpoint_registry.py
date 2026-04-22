from __future__ import annotations

"""Checkpoint → graph profile registry (OSS #49). Hot reload via POST /v1/admin/checkpoint-profiles/reload."""


import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_registry: dict[str, Any] | None = None
_REGISTRY_PATH = Path(__file__).resolve().parent.parent.parent / "rules" / "checkpoint_profiles_v1.json"


def load_checkpoint_registry() -> dict[str, Any]:
    global _registry
    if _registry is not None:
        return _registry
    if not _REGISTRY_PATH.is_file():
        log.warning("checkpoint registry missing: %s — using built-in default", _REGISTRY_PATH)
        _registry = {
            "version": 1,
            "default_profile": "standard",
            "profiles": {
                "minimal": {"risk_score_multiplier": 0.35, "max_neighbor_hops": 2},
                "standard": {"risk_score_multiplier": 1.0, "max_neighbor_hops": 3},
                "deep": {"risk_score_multiplier": 1.0, "max_neighbor_hops": 5},
            },
        }
        return _registry
    try:
        _registry = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("failed to load checkpoint registry: %s", e)
        _registry = {"version": 1, "default_profile": "standard", "profiles": {}}
    return _registry


def reload_checkpoint_registry() -> None:
    global _registry
    _registry = None
    load_checkpoint_registry()


def resolve_profile(checkpoint: str | None) -> dict[str, Any]:
    """Return profile dict; unknown checkpoint → default_profile."""
    data = load_checkpoint_registry()
    default_name = str(data.get("default_profile") or "standard")
    profiles: dict[str, Any] = dict(data.get("profiles") or {})
    name = (checkpoint or "").strip() or default_name
    if name not in profiles:
        name = default_name
    prof = dict(profiles.get(name) or {})
    prof["_profile_name"] = name
    prof.setdefault("risk_score_multiplier", 1.0)
    prof.setdefault("max_neighbor_hops", 3)
    return prof


def registry_public_view() -> dict[str, Any]:
    data = load_checkpoint_registry()
    return {
        "version": data.get("version", 1),
        "default_profile": data.get("default_profile", "standard"),
        "profiles": {k: {kk: vv for kk, vv in v.items() if not str(kk).startswith("_")} for k, v in (data.get("profiles") or {}).items()},
    }
