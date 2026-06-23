"""PLG industry starter templates — visual-rule JSON AST (flat leaves only for JSON compile path).

Each value is a ``VisualAstPack``-compatible dict (``name``, ``rules``, ``tag_rules``) matching
``decision_api.rule_compiler_api.VisualAstPack`` / ``VisualAstRule`` / ``VisualAstLeaf``.

Ingest / feature-service notes (pipeline fields referenced by templates):

- ``same_ip_decline_ratio_1h``: rolling ratio of declined card authorizations vs attempts from the
  same IP in the last hour (float 0..1). Populate from your card-processor webhooks + IP rollup.
"""

from __future__ import annotations

from typing import Any

# Stable keys for idempotent bootstrap / audit rows.
INDUSTRY_TEMPLATE_KEYS: tuple[str, ...] = (
    "plg_ato_velocity",
    "plg_card_testing_same_ip_declines",
    "plg_synthetic_id_impossible_geo",
    "plg_high_value_transfer_vpn",
    "plg_high_value_transfer_proxy",
)

# Five production-oriented starter packs (JSON AST). Each compiles to JSON rules via
# ``compile_visual_ast_pack_dict`` in decision-api.
INDUSTRY_RULE_TEMPLATE_ASTS: dict[str, dict[str, Any]] = {
    "plg_ato_velocity": {
        "name": "PLG — Account Takeover (Velocity)",
        "rules": [
            {
                "id": "plg_ato_velocity_login_window",
                "all_of": [
                    {"op": "gte", "field": "event_count_1h", "value": 18},
                    {"op": "gte", "field": "distinct_ip_address_24h", "value": 5},
                    {"op": "gte", "field": "distinct_device_id_24h", "value": 2},
                ],
                "any_of": [],
                "tags": ["industry:ato_velocity", "risk:session_takeover_candidate"],
                "score_delta": 38.0,
                "description": (
                    "Spike in hourly activity with many distinct IPs and devices in 24h — "
                    "common when credentials are tested or an account is being walked."
                ),
            }
        ],
        "tag_rules": [],
    },
    "plg_card_testing_same_ip_declines": {
        "name": "PLG — Card Testing (Same-IP Decline Concentration)",
        "rules": [
            {
                "id": "plg_card_testing_high_decline_ratio_same_ip",
                "all_of": [
                    {"op": "gte", "field": "same_ip_decline_ratio_1h", "value": 0.65},
                    {"op": "gte", "field": "event_count_1h", "value": 12},
                ],
                "any_of": [],
                "tags": ["industry:card_testing", "risk:card_testing_same_ip"],
                "score_delta": 42.0,
                "description": (
                    "High decline rate from the same IP with elevated attempt volume — "
                    "requires ``same_ip_decline_ratio_1h`` from your auth/card rail rollup."
                ),
            }
        ],
        "tag_rules": [],
    },
    "plg_synthetic_id_impossible_geo": {
        "name": "PLG — Synthetic ID (Impossible Geo-Velocity)",
        "rules": [
            {
                "id": "plg_synthetic_geo_velocity_new_account",
                "all_of": [
                    {"op": "gte", "field": "impossible_travel_risk", "value": 0.82},
                    {"op": "lte", "field": "account_age_days", "value": 30},
                ],
                "any_of": [],
                "tags": ["industry:synthetic_id_geo", "risk:identity_geo_anomaly"],
                "score_delta": 40.0,
                "description": (
                    "Location service impossible-travel signal on a young account — tune "
                    "``account_age_days`` and threshold once location-eval is wired."
                ),
            }
        ],
        "tag_rules": [],
    },
    "plg_high_value_transfer_vpn": {
        "name": "PLG — High-Value Transfer from VPN",
        "rules": [
            {
                "id": "plg_hv_payment_vpn",
                "all_of": [
                    {"op": "gte", "field": "amount", "value": 7500},
                    {"op": "is_true", "field": "is_vpn"},
                ],
                "any_of": [],
                "tags": ["industry:hv_transfer_anon_network", "risk:hv_transfer_vpn"],
                "score_delta": 28.0,
                "description": "Large normalized USD amount with VPN device/IP signal from SDK / OSINT.",
            }
        ],
        "tag_rules": [],
    },
    "plg_high_value_transfer_proxy": {
        "name": "PLG — High-Value Transfer from Proxy",
        "rules": [
            {
                "id": "plg_hv_payment_proxy_ip",
                "all_of": [
                    {"op": "gte", "field": "amount", "value": 7500},
                    {"op": "is_true", "field": "ip_is_proxy"},
                ],
                "any_of": [],
                "tags": ["industry:hv_transfer_anon_network", "risk:hv_transfer_proxy"],
                "score_delta": 26.0,
                "description": "Large normalized USD amount with proxy-class IP from enrichment.",
            }
        ],
        "tag_rules": [],
    },
}


def list_industry_template_items() -> list[tuple[str, dict[str, Any]]]:
    """Deterministic iteration order matching :data:`INDUSTRY_TEMPLATE_KEYS`."""
    return [(k, INDUSTRY_RULE_TEMPLATE_ASTS[k]) for k in INDUSTRY_TEMPLATE_KEYS]
