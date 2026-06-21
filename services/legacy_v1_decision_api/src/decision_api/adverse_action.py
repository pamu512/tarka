"""Map internal rule hits to standardized adverse-action style codes (FCRA/ECOA reporting)."""

from __future__ import annotations

import json
import logging
from typing import Any

from decision_api.config import settings

log = logging.getLogger(__name__)

_MAX_CODES = 4
_G99_FALLBACK = "G99: Internal Policy"

_DEFAULT_MAP: dict[str, str] = {
    "velocity_high": "V01: Excessive recent activity",
    "graph_network_risk": "V02: Network risk indicator",
    "blacklist_block": "V03: Internal risk policy",
    "consortium_shared_signal": "V04: Cross-tenant risk signal",
    "device_intelligence_risk": "V05: Device reputation concern",
    "external_signal_risk": "V06: Third-party risk signal",
}

# Lower rank = higher priority when selecting up to _MAX_CODES disclosures.
_HIT_SEVERITY_RANK: dict[str, int] = {
    "blacklist_block": 0,
    "device_intelligence_risk": 5,
    "graph_network_risk": 10,
    "external_signal_risk": 15,
    "consortium_shared_signal": 20,
    "velocity_high": 30,
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
    """Return up to four mapped codes in severity order; G99 when hits exist but nothing maps."""
    mapping = _rule_to_code_map()
    if not rule_hits:
        return []

    indexed = list(enumerate(rule_hits))
    indexed.sort(key=lambda pair: (_HIT_SEVERITY_RANK.get(pair[1], 100), pair[0]))

    out: list[str] = []
    seen: set[str] = set()
    for _, hit in indexed:
        code = mapping.get(hit)
        if not code:
            log.warning(
                "adverse_action: rule hit %r has no mapped adverse-action code", hit
            )
            continue
        if code in seen:
            continue
        seen.add(code)
        out.append(code)
        if len(out) >= _MAX_CODES:
            break

    if not out:
        log.warning(
            "adverse_action: no mapped codes for non-empty rule_hits; using G99 fallback"
        )
        return [_G99_FALLBACK]

    return out
