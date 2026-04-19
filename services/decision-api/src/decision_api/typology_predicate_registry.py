"""OSS #46 — versioned predicate registry for typology DSL (named conditions, pin-able versions)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from decision_api.config import settings

log = logging.getLogger(__name__)

_REGISTRY: dict[str, Any] | None = None


def registry_path() -> Path:
    return Path(settings.rules_path) / "typology_predicate_registry_v1.json"


def load_predicate_registry() -> dict[str, Any]:
    global _REGISTRY
    if _REGISTRY is not None:
        return _REGISTRY
    p = registry_path()
    if not p.is_file():
        log.warning("typology predicate registry not found: %s — predicate_ref disabled", p)
        _REGISTRY = {"registry_id": "none", "version": 0, "predicates": []}
        return _REGISTRY
    try:
        _REGISTRY = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("failed to load predicate registry: %s", e)
        _REGISTRY = {"registry_id": "none", "version": 0, "predicates": []}
    return _REGISTRY


def reload_predicate_registry() -> None:
    global _REGISTRY
    _REGISTRY = None
    load_predicate_registry()


def predicate_when_by_id(registry: dict[str, Any], predicate_id: str) -> dict[str, Any] | None:
    for p in registry.get("predicates") or []:
        if str(p.get("id") or "") == predicate_id:
            when = p.get("when")
            return when if isinstance(when, dict) else None
    return None


def registry_public_view() -> dict[str, Any]:
    data = load_predicate_registry()
    preds = []
    for p in data.get("predicates") or []:
        pid = str(p.get("id") or "")
        if not pid:
            continue
        preds.append(
            {
                "id": pid,
                "description": p.get("description", ""),
                "when": p.get("when"),
            }
        )
    return {
        "registry_id": data.get("registry_id", "unknown"),
        "version": data.get("version", 0),
        "predicates": preds,
    }
