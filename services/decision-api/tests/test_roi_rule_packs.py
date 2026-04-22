from __future__ import annotations

"""Regression tests for ROI rule packs (horizontal burst, vertical payment, shadow probe)."""


from pathlib import Path
from unittest.mock import patch

from decision_api.json_rules import evaluate_json_rules, get_shadow_packs, load_rules
from decision_api.simulation_api import _eval_with_override_rules
from decision_api.vertical_packs import get_vertical_pack

_RULES_DIR = Path(__file__).resolve().parent.parent / "rules"


class TestROIRulePacksLoaded:
    def test_shipped_packs_parse_and_load(self) -> None:
        with patch("decision_api.json_rules.settings") as mock_settings:
            mock_settings.rules_path = _RULES_DIR
            load_rules()
            from decision_api.json_rules import _cached_packs

            rule_ids: list[str] = []
            for pack in _cached_packs:
                for r in pack.get("rules", []):
                    rule_ids.append(r["id"])
            assert "burst_5m_severe" in rule_ids
            assert "pay_high_amount_untrusted_device" in rule_ids

    def test_shadow_probe_pack_is_shadow_not_active(self) -> None:
        with patch("decision_api.json_rules.settings") as mock_settings:
            mock_settings.rules_path = _RULES_DIR
            load_rules()
            from decision_api.json_rules import _cached_packs

            active_ids = {r["id"] for p in _cached_packs for r in p.get("rules", [])}
            assert "shadow_probe_high_amount_only" not in active_ids

            shadow = get_shadow_packs()
            shadow_ids: list[str] = []
            for p in shadow:
                for r in p.get("rules", []):
                    shadow_ids.append(r["id"])
            assert "shadow_probe_high_amount_only" in shadow_ids


class TestROIRuleEvaluation:
    def test_burst_5m_and_vertical_tags(self) -> None:
        with patch("decision_api.json_rules.settings") as mock_settings:
            mock_settings.rules_path = _RULES_DIR
            load_rules()
        feats = {
            "amount": 20_000,
            "is_vpn": True,
            "is_emulator": False,
            "is_bot": False,
            "is_new_device": True,
            "event_count_5m": 16,
            "transaction_count_24h": 30,
        }
        hits, tags, delta, _pf = evaluate_json_rules(feats, [])
        assert "burst_5m_severe" in hits
        assert "pay_high_amount_untrusted_device" in hits
        assert delta > 0
        assert any("horizontal:burst_5m" in t for t in tags)
        assert any("vertical:payment" in t for t in tags)

    def test_vertical_pack_events_trigger_expected_prefix_tags(self) -> None:
        scenarios = {
            "fintech": {"amount": 2500, "account_age_days": 3, "transaction_count_24h": 1},
            "ecommerce": {"is_bot": True, "amount": 180, "distinct_countries_7d": 1, "transaction_count_24h": 1},
            "gaming": {"is_emulator": True, "is_bot": True, "hour_of_day": 1, "transaction_count_24h": 2},
        }
        for vertical, payload in scenarios.items():
            pack = get_vertical_pack(vertical)
            assert pack is not None
            out = _eval_with_override_rules({"payload": payload}, pack["rules"])
            assert len(out["rule_hits"]) >= 1
            assert any(hit.startswith(vertical[:3]) for hit in out["rule_hits"])
