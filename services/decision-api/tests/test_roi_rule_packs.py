"""Regression tests for ROI rule packs (horizontal burst, vertical payment, shadow probe)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from decision_api.json_rules import evaluate_json_rules, get_shadow_packs, load_rules

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
        hits, tags, delta = evaluate_json_rules(feats, [])
        assert "burst_5m_severe" in hits
        assert "pay_high_amount_untrusted_device" in hits
        assert delta > 0
        assert any("horizontal:burst_5m" in t for t in tags)
        assert any("vertical:payment" in t for t in tags)
