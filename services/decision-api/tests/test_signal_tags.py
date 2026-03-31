"""Unit tests for signal tag extraction and score blending."""
from decision_api.main import extract_signal_tags, _blend_scores


class TestExtractSignalTags:
    def test_none_context(self):
        assert extract_signal_tags(None) == []

    def test_empty_signals(self):
        assert extract_signal_tags({"signals": {}}) == []

    def test_all_false(self):
        ctx = {"signals": {
            "is_emulator": False,
            "is_vpn": False,
            "is_bot": False,
        }}
        assert extract_signal_tags(ctx) == []

    def test_single_flag(self):
        ctx = {"signals": {"is_vpn": True}}
        assert extract_signal_tags(ctx) == ["sdk:vpn"]

    def test_multiple_flags(self):
        ctx = {"signals": {
            "is_emulator": True,
            "is_bot": True,
            "webdriver_detected": True,
            "is_vpn": False,
        }}
        tags = extract_signal_tags(ctx)
        assert "sdk:emulator" in tags
        assert "sdk:bot" in tags
        assert "sdk:webdriver" in tags
        assert "sdk:vpn" not in tags

    def test_all_flags(self):
        ctx = {"signals": {
            "is_emulator": True,
            "is_vpn": True,
            "is_bot": True,
            "is_repackaged": True,
            "is_spoofed_location": True,
            "webdriver_detected": True,
            "headless_detected": True,
            "automation_detected": True,
            "timezone_geo_mismatch": True,
            "vpn_interface_detected": True,
            "mock_location_detected": True,
            "ip_is_proxy": True,
            "ip_is_datacenter": True,
        }}
        tags = extract_signal_tags(ctx)
        assert len(tags) == 13

    def test_non_bool_ignored(self):
        ctx = {"signals": {"is_vpn": 1, "is_bot": "yes"}}
        assert extract_signal_tags(ctx) == []

    def test_missing_signals_key(self):
        assert extract_signal_tags({"device_id": "abc"}) == []


class TestBlendScores:
    def test_average_strategy(self):
        from unittest.mock import patch
        with patch("decision_api.main.settings") as s:
            s.score_blend_strategy = "average"
            assert _blend_scores(60.0, 80.0) == 70.0

    def test_max_strategy(self):
        from unittest.mock import patch
        with patch("decision_api.main.settings") as s:
            s.score_blend_strategy = "max"
            assert _blend_scores(60.0, 80.0) == 80.0

    def test_rules_only_strategy(self):
        from unittest.mock import patch
        with patch("decision_api.main.settings") as s:
            s.score_blend_strategy = "rules_only"
            assert _blend_scores(60.0, 80.0) == 60.0

    def test_none_ml_score(self):
        from unittest.mock import patch
        with patch("decision_api.main.settings") as s:
            s.score_blend_strategy = "average"
            assert _blend_scores(60.0, None) == 60.0

    def test_clamp_high(self):
        from unittest.mock import patch
        with patch("decision_api.main.settings") as s:
            s.score_blend_strategy = "average"
            assert _blend_scores(120.0, 200.0) == 100.0

    def test_clamp_low(self):
        from unittest.mock import patch
        with patch("decision_api.main.settings") as s:
            s.score_blend_strategy = "average"
            assert _blend_scores(-50.0, None) == 0.0
