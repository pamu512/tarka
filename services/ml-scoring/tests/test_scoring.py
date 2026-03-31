"""Unit tests for ML scoring — adaptive detector and explainability."""
import json
import os
import tempfile

import pytest

from ml_scoring.adaptive import OnlineAnomalyDetector
from ml_scoring.explainability import explain_score
from ml_scoring.main import _heuristic_score, _safe_float


# ---------- OnlineAnomalyDetector ----------


class TestOnlineAnomalyDetector:
    def test_partial_fit_increments_count(self):
        det = OnlineAnomalyDetector(alpha=0.1)
        assert det._count == 0
        det.partial_fit({"amount": 100.0, "hour": 12.0})
        assert det._count == 1
        det.partial_fit({"amount": 200.0, "hour": 14.0})
        assert det._count == 2

    def test_score_insufficient_data(self):
        det = OnlineAnomalyDetector(alpha=0.1)
        for _ in range(5):
            det.partial_fit({"x": 1.0})
        score, contribs = det.score({"x": 100.0})
        assert score == 50.0
        assert contribs[0]["feature"] == "insufficient_data"

    def test_score_after_enough_observations(self):
        det = OnlineAnomalyDetector(alpha=0.1)
        for i in range(20):
            det.partial_fit({"amount": 100.0 + i, "hour": 12.0})
        score, contribs = det.score({"amount": 100.0, "hour": 12.0})
        assert 0.0 <= score <= 100.0

    def test_score_anomalous_value_scores_higher(self):
        det = OnlineAnomalyDetector(alpha=0.05)
        for _ in range(50):
            det.partial_fit({"amount": 100.0})
        normal_score, _ = det.score({"amount": 100.0})
        anomaly_score, _ = det.score({"amount": 99999.0})
        assert anomaly_score > normal_score

    def test_save_and_load_round_trip(self):
        det = OnlineAnomalyDetector(alpha=0.05)
        for i in range(15):
            det.partial_fit({"val": float(i * 10)})

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "state.json")
            det.save(path)

            assert os.path.exists(path)
            with open(path) as f:
                data = json.load(f)
            assert data["count"] == 15
            assert "val" in data["mean"]

            det2 = OnlineAnomalyDetector()
            det2.load(path)
            assert det2._count == 15
            assert abs(det2._mean["val"] - det._mean["val"]) < 1e-6

    def test_load_nonexistent_path_is_noop(self):
        det = OnlineAnomalyDetector()
        det.load("/nonexistent/path/detector.json")
        assert det._count == 0

    def test_get_stats(self):
        det = OnlineAnomalyDetector(alpha=0.02)
        det.partial_fit({"a": 1.0, "b": 2.0})
        stats = det.get_stats()
        assert stats["observations"] == 1
        assert stats["tracked_features"] == 2
        assert stats["alpha"] == 0.02

    def test_partial_fit_skips_nan(self):
        det = OnlineAnomalyDetector(alpha=0.1)
        det.partial_fit({"good": 1.0, "bad": float("nan")})
        assert det._count == 1
        assert "good" in det._mean
        assert "bad" not in det._mean


# ---------- explain_score ----------


class TestExplainScore:
    def test_high_amount_triggers_reason(self):
        reasons = explain_score(60.0, {"amount": 10000})
        codes = [r["code"] for r in reasons]
        assert "HIGH_AMOUNT" in codes

    def test_elevated_amount_triggers_reason(self):
        reasons = explain_score(30.0, {"amount": 2000})
        codes = [r["code"] for r in reasons]
        assert "ELEVATED_AMOUNT" in codes

    def test_signal_explanations(self):
        reasons = explain_score(40.0, {"is_emulator": True, "is_vpn": True, "is_bot": True})
        codes = [r["code"] for r in reasons]
        assert "EMULATOR_DETECTED" in codes
        assert "VPN_DETECTED" in codes
        assert "BOT_DETECTED" in codes

    def test_critical_risk_threshold(self):
        reasons = explain_score(85.0, {"amount": 100})
        codes = [r["code"] for r in reasons]
        assert "CRITICAL_RISK" in codes

    def test_elevated_risk_threshold(self):
        reasons = explain_score(55.0, {"amount": 100})
        codes = [r["code"] for r in reasons]
        assert "ELEVATED_RISK" in codes

    def test_low_score_no_risk_label(self):
        reasons = explain_score(10.0, {"amount": 50})
        codes = [r["code"] for r in reasons]
        assert "CRITICAL_RISK" not in codes
        assert "ELEVATED_RISK" not in codes

    def test_adaptive_contributions_included(self):
        contribs = [{"feature": "amount", "value": 50000, "expected_mean": 500, "z_score": 4.5}]
        reasons = explain_score(70.0, {}, adaptive_contributions=contribs)
        codes = [r["code"] for r in reasons]
        assert "ANOMALY_AMOUNT" in codes

    def test_velocity_feature(self):
        reasons = explain_score(40.0, {"txn_count_24h": 50})
        codes = [r["code"] for r in reasons]
        assert "HIGH_TXN_COUNT_24H" in codes


# ---------- _heuristic_score ----------


class TestHeuristicScore:
    def test_base_score_low_risk(self):
        score = _heuristic_score({})
        assert score == 10.0

    def test_high_amount(self):
        score = _heuristic_score({"amount": 60000})
        assert score > 50

    def test_bot_and_emulator(self):
        score = _heuristic_score({"is_bot": True, "is_emulator": True})
        assert score >= 45

    def test_night_hours(self):
        score = _heuristic_score({"hour_of_day": 3})
        assert score > 10

    def test_new_account_high_velocity(self):
        score = _heuristic_score({
            "account_age_days": 2,
            "transaction_count_24h": 25,
            "distinct_countries_7d": 5,
        })
        assert score >= 42

    def test_score_clamped_to_100(self):
        score = _heuristic_score({
            "amount": 100000,
            "is_bot": True,
            "is_emulator": True,
            "is_vpn": True,
            "is_new_device": True,
            "hour_of_day": 3,
            "transaction_count_24h": 50,
            "distinct_countries_7d": 10,
            "account_age_days": 1,
        })
        assert score <= 100.0
