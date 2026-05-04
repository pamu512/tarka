"""Configurable queue / team routing from JSON rules (no raw OPA required for v1)."""

from __future__ import annotations

import json
import logging
from typing import Any

from case_api.config import settings

log = logging.getLogger(__name__)


def _rules() -> list[dict[str, Any]]:
    raw = settings.case_queue_routing_rules_json or ""
    if not str(raw).strip():
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError as e:
        log.warning("case_queue_routing_rules_json invalid: %s", e)
        return []


def evaluate_case_routing(case_payload: dict[str, Any]) -> str | None:
    """Return ``assigned_team`` when a rule matches; else None (caller keeps default)."""
    for rule in _rules():
        when = rule.get("when") or {}
        ok = True
        for k, want in when.items():
            if case_payload.get(k) != want:
                ok = False
                break
        if ok:
            team = rule.get("assigned_team")
            if isinstance(team, str) and team.strip():
                return team.strip()
    return None
