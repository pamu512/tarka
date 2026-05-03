"""Map internal rule hits to standardized adverse-action style codes (FCRA/ECOA reporting)."""

from __future__ import annotations

import json
import logging
from typing import Any

from decision_api.config import settings

log = logging.getLogger(__name__)

_DEFAULT_MAP: dict[str, str] = {
    "velocity_high": "V01: Excessive recent activity",
    "graph_network_risk": "V02: Network risk indicator",
    "blacklist_block": "V03: Internal risk policy",
    "consortium_shared_signal": "V04: Cross-tenant risk signal",
    "device_intelligence_risk": "V05: Device reputation concern",
    "external_signal_risk": "V06: Third-party risk signal",
}


def _rule_to_code_map() -> dict[str, str]:
    raw = (settings.adverse_action_rule_map_json or "").strip()
    if not raw:
        return dict(_DEFAULT_MAP)
    try:
        parsed: Any = json.loads(raw)
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items()}
    except Exception as exc:
        log.warning("adverse_action_rule_map_json invalid, using defaults: %s", exc)
    return dict(_DEFAULT_MAP)


def adverse_action_codes_for_hits(rule_hits: list[str]) -> list[str]:
    mapping = _rule_to_code_map()
    out: list[str] = []
    seen: set[str] = set()
    for hit in rule_hits:
        code = mapping.get(hit)
        if code and code not in seen:
            seen.add(code)
            out.append(code)
    return out
