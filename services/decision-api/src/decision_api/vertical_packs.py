from __future__ import annotations

from typing import Any

_VELOCITY_PRESETS: dict[str, list[dict[str, Any]]] = {
    "standard": [
        {"name": "burst_5m", "feature": "event_count_5m", "window_seconds": 300},
        {"name": "hourly_1h", "feature": "event_count_1h", "window_seconds": 3600},
        {"name": "daily_24h", "feature": "event_count_24h", "window_seconds": 86400},
    ],
}

# Kill criteria: do not promote a pack when simulation metrics fall outside bands.
_DEFAULT_KILL: dict[str, Any] = {
    "min_events": 100,
    "min_precision": 0.01,
    "min_recall": 0.01,
    "max_false_positive_rate": 0.95,
    "notes": [
        "Do not promote when low_sample_warning is true.",
        "Do not treat synthetic precision/recall as production KPIs without labeled holdouts.",
    ],
}

_PACKS: dict[str, dict[str, Any]] = {
    "fintech": {
        "name": "Vertical Fintech Starter",
        "version": 1,
        "velocity_presets": "standard",
        "kill_criteria": {
            **_DEFAULT_KILL,
            "min_precision": 0.015,
            "min_recall": 0.02,
        },
        "rules": [
            {
                "id": "fin_high_amount_new_account",
                "when": [
                    {"field": "amount", "op": "gte", "value": 2000},
                    {"field": "account_age_days", "op": "lte", "value": 14},
                ],
                "tags": ["vertical:fintech", "risk:high_amount_new_account"],
                "score_delta": 28,
                "description": "Large transfer from a young account",
            },
            {
                "id": "fin_velocity_spike",
                "when": [{"field": "transaction_count_24h", "op": "gte", "value": 18}],
                "tags": ["vertical:fintech", "risk:velocity_spike"],
                "score_delta": 18,
                "description": "Unusual transaction velocity",
            },
        ],
        "tag_rules": [],
    },
    "ecommerce": {
        "name": "Vertical E-commerce Starter",
        "version": 1,
        "velocity_presets": "standard",
        "kill_criteria": {**_DEFAULT_KILL, "min_precision": 0.015, "min_recall": 0.02},
        "rules": [
            {
                "id": "eco_bot_checkout",
                "when": [
                    {"field": "is_bot", "op": "is_true", "value": True},
                    {"field": "amount", "op": "gte", "value": 150},
                ],
                "tags": ["vertical:ecommerce", "risk:bot_checkout"],
                "score_delta": 22,
                "description": "Checkout attempt with bot signal",
            },
            {
                "id": "eco_multi_geo_velocity",
                "when": [
                    {"field": "distinct_countries_7d", "op": "gte", "value": 3},
                    {"field": "transaction_count_24h", "op": "gte", "value": 12},
                ],
                "tags": ["vertical:ecommerce", "risk:multi_geo_velocity"],
                "score_delta": 20,
                "description": "Cross-border velocity pattern",
            },
        ],
        "tag_rules": [],
    },
    "gaming": {
        "name": "Vertical Gaming Starter",
        "version": 1,
        "velocity_presets": "standard",
        "kill_criteria": {**_DEFAULT_KILL, "min_precision": 0.015, "min_recall": 0.02},
        "rules": [
            {
                "id": "gam_emulator_bot",
                "when": [
                    {"field": "is_emulator", "op": "is_true", "value": True},
                    {"field": "is_bot", "op": "is_true", "value": True},
                ],
                "tags": ["vertical:gaming", "risk:emu_bot"],
                "score_delta": 30,
                "description": "Likely scripted gameplay abuse",
            },
            {
                "id": "gam_night_velocity",
                "when": [
                    {"field": "hour_of_day", "op": "lte", "value": 4},
                    {"field": "transaction_count_24h", "op": "gte", "value": 20},
                ],
                "tags": ["vertical:gaming", "risk:night_velocity"],
                "score_delta": 16,
                "description": "Off-hour farming/abuse pattern",
            },
        ],
        "tag_rules": [],
    },
}


def list_vertical_packs() -> dict[str, dict[str, Any]]:
    return {
        k: {
            "name": v["name"],
            "rules": len(v.get("rules", [])),
            "version": v.get("version", 1),
            "has_kill_criteria": bool(v.get("kill_criteria")),
        }
        for k, v in _PACKS.items()
    }


def evaluate_kill_criteria(
    metrics: dict[str, Any],
    kill: dict[str, Any] | None,
    *,
    events_evaluated: int,
) -> dict[str, Any]:
    """Return promote gate from simulation metrics vs pack kill_criteria."""
    criteria = dict(kill or _DEFAULT_KILL)
    blockers: list[str] = []
    precision = float(metrics.get("precision") or 0.0)
    recall = float(metrics.get("recall") or 0.0)
    fpr = float(metrics.get("false_positive_rate") or metrics.get("fpr") or 0.0)
    min_events = int(criteria.get("min_events") or 100)
    if events_evaluated < min_events:
        blockers.append(f"events_evaluated<{min_events}")
    if precision < float(criteria.get("min_precision") or 0.0):
        blockers.append("precision_below_min")
    if recall < float(criteria.get("min_recall") or 0.0):
        blockers.append("recall_below_min")
    max_fpr = criteria.get("max_false_positive_rate")
    if max_fpr is not None and fpr > float(max_fpr):
        blockers.append("false_positive_rate_above_max")
    return {
        "promote_allowed": len(blockers) == 0,
        "blockers": blockers,
        "kill_criteria": criteria,
        "notes": list(criteria.get("notes") or []),
    }


def get_vertical_pack(name: str) -> dict[str, Any] | None:
    pack = _PACKS.get(name.lower())
    if not pack:
        return None
    vp_key = pack.get("velocity_presets")
    presets = _VELOCITY_PRESETS.get(str(vp_key), []) if vp_key else []
    return {
        "name": pack["name"],
        "version": pack.get("version", 1),
        "velocity_presets": presets,
        "rules": [dict(r) for r in pack.get("rules", [])],
        "tag_rules": [dict(r) for r in pack.get("tag_rules", [])],
        "kill_criteria": dict(pack.get("kill_criteria") or _DEFAULT_KILL),
    }
