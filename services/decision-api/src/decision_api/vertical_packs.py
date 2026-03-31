from __future__ import annotations

from typing import Any

_PACKS: dict[str, dict[str, Any]] = {
    "fintech": {
        "name": "Vertical Fintech Starter",
        "version": 1,
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
    return {k: {"name": v["name"], "rules": len(v.get("rules", [])), "version": v.get("version", 1)} for k, v in _PACKS.items()}


def get_vertical_pack(name: str) -> dict[str, Any] | None:
    pack = _PACKS.get(name.lower())
    if not pack:
        return None
    return {
        "name": pack["name"],
        "version": pack.get("version", 1),
        "rules": [dict(r) for r in pack.get("rules", [])],
        "tag_rules": [dict(r) for r in pack.get("tag_rules", [])],
    }
