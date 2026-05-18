"""Unit tests for json_rules engine."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from decision_api.json_rules import (
    _match_condition,
    evaluate_json_rules,
    load_rules,
)

# ---- _match_condition ----


class TestMatchCondition:
    def test_eq_match(self):
        assert (
            _match_condition(
                {"country": "US"}, {"field": "country", "op": "eq", "value": "US"}
            )
            is True
        )

    def test_eq_mismatch(self):
        assert (
            _match_condition(
                {"country": "UK"}, {"field": "country", "op": "eq", "value": "US"}
            )
            is False
        )

    def test_eq_missing_field(self):
        assert (
            _match_condition({}, {"field": "country", "op": "eq", "value": "US"})
            is False
        )

    def test_gte_match(self):
        assert (
            _match_condition(
                {"amount": 5000}, {"field": "amount", "op": "gte", "value": 1000}
            )
            is True
        )

    def test_gte_equal(self):
        assert (
            _match_condition(
                {"amount": 1000}, {"field": "amount", "op": "gte", "value": 1000}
            )
            is True
        )

    def test_gte_fail(self):
        assert (
            _match_condition(
                {"amount": 500}, {"field": "amount", "op": "gte", "value": 1000}
            )
            is False
        )

    def test_gte_none(self):
        assert (
            _match_condition({}, {"field": "amount", "op": "gte", "value": 1000})
            is False
        )

    def test_lte_match(self):
        assert (
            _match_condition(
                {"amount": 500}, {"field": "amount", "op": "lte", "value": 1000}
            )
            is True
        )

    def test_lte_fail(self):
        assert (
            _match_condition(
                {"amount": 5000}, {"field": "amount", "op": "lte", "value": 1000}
            )
            is False
        )

    def test_in_match(self):
        assert (
            _match_condition(
                {"country": "US"},
                {"field": "country", "op": "in", "value": ["US", "UK"]},
            )
            is True
        )

    def test_in_fail(self):
        assert (
            _match_condition(
                {"country": "FR"},
                {"field": "country", "op": "in", "value": ["US", "UK"]},
            )
            is False
        )

    def test_in_none_value(self):
        assert (
            _match_condition(
                {"country": "US"}, {"field": "country", "op": "in", "value": None}
            )
            is False
        )

    def test_contains_match(self):
        assert (
            _match_condition(
                {"email": "user@test.com"},
                {"field": "email", "op": "contains", "value": "test"},
            )
            is True
        )

    def test_contains_fail(self):
        assert (
            _match_condition(
                {"email": "user@real.com"},
                {"field": "email", "op": "contains", "value": "test"},
            )
            is False
        )

    def test_is_true(self):
        assert (
            _match_condition({"is_vpn": True}, {"field": "is_vpn", "op": "is_true"})
            is True
        )

    def test_is_true_false_value(self):
        assert (
            _match_condition({"is_vpn": False}, {"field": "is_vpn", "op": "is_true"})
            is False
        )

    def test_is_true_truthy_not_bool(self):
        assert (
            _match_condition({"is_vpn": 1}, {"field": "is_vpn", "op": "is_true"})
            is False
        )

    def test_is_false(self):
        assert (
            _match_condition({"is_vpn": False}, {"field": "is_vpn", "op": "is_false"})
            is True
        )

    def test_unknown_op(self):
        assert (
            _match_condition({"x": 1}, {"field": "x", "op": "magic", "value": 1})
            is False
        )

    def test_missing_field_key(self):
        assert _match_condition({"x": 1}, {"op": "eq", "value": 1}) is False

    def test_default_op_is_eq(self):
        assert _match_condition({"x": 1}, {"field": "x", "value": 1}) is True


# ---- load_rules ----


class TestLoadRules:
    def test_load_from_dir(self):
        pack = {
            "version": 1,
            "rules": [
                {
                    "id": "r1",
                    "when": [{"field": "amount", "op": "gte", "value": 9000}],
                    "tags": ["high_amount"],
                    "score_delta": 20,
                }
            ],
            "tag_rules": [],
        }
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "test_pack.json").write_text(json.dumps(pack))
            with patch("decision_api.json_rules.settings") as mock_settings:
                mock_settings.rules_path = d
                load_rules()
                from decision_api.json_rules import _cached_packs

                assert len(_cached_packs) == 1
                assert _cached_packs[0]["rules"][0]["id"] == "r1"

    def test_load_empty_dir(self):
        with tempfile.TemporaryDirectory() as d:
            with patch("decision_api.json_rules.settings") as mock_settings:
                mock_settings.rules_path = d
                load_rules()
                from decision_api.json_rules import _cached_packs

                assert len(_cached_packs) == 0

    def test_load_nonexistent_dir(self):
        with patch("decision_api.json_rules.settings") as mock_settings:
            mock_settings.rules_path = "/nonexistent/path/xyz"
            load_rules()
            from decision_api.json_rules import _cached_packs

            assert len(_cached_packs) == 0

    def test_skip_bad_json(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "bad.json").write_text("NOT JSON {{{")
            (Path(d) / "good.json").write_text(
                json.dumps({"version": 1, "rules": [], "tag_rules": []})
            )
            with patch("decision_api.json_rules.settings") as mock_settings:
                mock_settings.rules_path = d
                load_rules()
                from decision_api.json_rules import _cached_packs

                assert len(_cached_packs) == 1

    def test_skip_wrong_version(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "v2.json").write_text(json.dumps({"version": 2, "rules": []}))
            with patch("decision_api.json_rules.settings") as mock_settings:
                mock_settings.rules_path = d
                load_rules()
                from decision_api.json_rules import _cached_packs

                assert len(_cached_packs) == 0


# ---- evaluate_json_rules ----


class TestEvaluateJsonRules:
    def _load_pack(self, pack):
        import decision_api.json_rules as mod

        mod._cached_packs = [pack]

    def test_single_rule_hit(self):
        self._load_pack(
            {
                "_source_file": "rules_live.json",
                "version": 1,
                "rules": [
                    {
                        "id": "big_tx",
                        "when": [{"field": "amount", "op": "gte", "value": 5000}],
                        "tags": ["high_amount"],
                        "score_delta": 20,
                    }
                ],
                "tag_rules": [],
            }
        )
        hits, tags, delta, contributing = evaluate_json_rules({"amount": 10000}, [])
        assert hits == ["big_tx"]
        assert tags == ["high_amount"]
        assert delta == 20.0
        assert contributing == ["rules_live.json"]
        from decision_api.json_rules import get_rule_hit_telemetry

        snap = get_rule_hit_telemetry()
        assert snap["total_hits"] >= 1
        assert any(r["rule_id"] == "big_tx" and r["hits"] >= 1 for r in snap["rows"])

    def test_no_hit(self):
        self._load_pack(
            {
                "version": 1,
                "rules": [
                    {
                        "id": "big_tx",
                        "when": [{"field": "amount", "op": "gte", "value": 5000}],
                        "tags": ["high_amount"],
                        "score_delta": 20,
                    }
                ],
                "tag_rules": [],
            }
        )
        hits, tags, delta, contributing = evaluate_json_rules({"amount": 100}, [])
        assert hits == []
        assert tags == []
        assert delta == 0.0
        assert contributing == []

    def test_multi_condition_all_match(self):
        self._load_pack(
            {
                "version": 1,
                "rules": [
                    {
                        "id": "combo",
                        "when": [
                            {"field": "amount", "op": "gte", "value": 5000},
                            {"field": "is_vpn", "op": "is_true"},
                        ],
                        "tags": ["suspicious"],
                        "score_delta": 30,
                    }
                ],
                "tag_rules": [],
            }
        )
        hits, tags, delta, _contributing = evaluate_json_rules(
            {"amount": 6000, "is_vpn": True}, []
        )
        assert hits == ["combo"]

    def test_multi_condition_partial_match(self):
        self._load_pack(
            {
                "version": 1,
                "rules": [
                    {
                        "id": "combo",
                        "when": [
                            {"field": "amount", "op": "gte", "value": 5000},
                            {"field": "is_vpn", "op": "is_true"},
                        ],
                        "tags": ["suspicious"],
                        "score_delta": 30,
                    }
                ],
                "tag_rules": [],
            }
        )
        hits, tags, delta, _contributing = evaluate_json_rules(
            {"amount": 6000, "is_vpn": False}, []
        )
        assert hits == []

    def test_tag_rules(self):
        self._load_pack(
            {
                "version": 1,
                "rules": [],
                "tag_rules": [
                    {
                        "id": "escalate_vpn",
                        "any_tag": ["sdk:vpn"],
                        "tags": ["escalated"],
                        "score_delta": 10,
                    }
                ],
            }
        )
        hits, tags, delta, _contributing = evaluate_json_rules(
            {}, ["sdk:vpn", "sdk:emulator"]
        )
        assert hits == ["escalate_vpn"]
        assert tags == ["escalated"]
        assert delta == 10.0

    def test_signal_tags_merge_for_tag_rules(self):
        """Request-scoped tags (replay, geo) participate in tag_rules without Redis."""
        self._load_pack(
            {
                "version": 1,
                "rules": [],
                "tag_rules": [
                    {
                        "id": "replay_escalation",
                        "any_tag": ["ingress:replay_payload"],
                        "tags": ["policy:replay"],
                        "score_delta": 10,
                    }
                ],
            }
        )
        hits, tags, delta, _contributing = evaluate_json_rules(
            {}, [], signal_tags=["ingress:replay_payload"]
        )
        assert hits == ["replay_escalation"]
        assert "policy:replay" in tags
        assert delta == 10.0

    def test_tag_rules_no_match(self):
        self._load_pack(
            {
                "version": 1,
                "rules": [],
                "tag_rules": [
                    {
                        "id": "escalate_vpn",
                        "any_tag": ["sdk:vpn"],
                        "tags": ["escalated"],
                        "score_delta": 10,
                    }
                ],
            }
        )
        hits, tags, delta, _contributing = evaluate_json_rules({}, ["sdk:emulator"])
        assert hits == []

    def test_empty_when_skipped(self):
        self._load_pack(
            {
                "version": 1,
                "rules": [
                    {"id": "bad_rule", "when": [], "tags": ["x"], "score_delta": 5}
                ],
                "tag_rules": [],
            }
        )
        hits, tags, delta, _contributing = evaluate_json_rules({"amount": 100}, [])
        assert hits == []

    def test_multiple_rules_accumulate(self):
        self._load_pack(
            {
                "version": 1,
                "rules": [
                    {
                        "id": "r1",
                        "when": [{"field": "is_bot", "op": "is_true"}],
                        "tags": ["bot"],
                        "score_delta": 40,
                    },
                    {
                        "id": "r2",
                        "when": [{"field": "is_vpn", "op": "is_true"}],
                        "tags": ["vpn"],
                        "score_delta": 15,
                    },
                ],
                "tag_rules": [],
            }
        )
        hits, tags, delta, _contributing = evaluate_json_rules(
            {"is_bot": True, "is_vpn": True}, []
        )
        assert hits == ["r1", "r2"]
        assert sorted(tags) == ["bot", "vpn"]
        assert delta == 55.0

    def test_empty_packs(self):
        import decision_api.json_rules as mod

        mod._cached_packs = []
        hits, tags, delta, _contributing = evaluate_json_rules({"amount": 999999}, [])
        assert hits == []
