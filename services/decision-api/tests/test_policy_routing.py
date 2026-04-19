"""Unit tests for OSS #31 policy routing helpers."""

from decision_api.policy_routing import (
    build_canary_cohort_audit,
    build_policy_routing_audit,
    cohort_bucket_0_99,
    decision_from_rule_score,
)


def test_cohort_bucket_stable():
    a = cohort_bucket_0_99("t1", "e1", "policy_v1")
    b = cohort_bucket_0_99("t1", "e1", "policy_v1")
    assert a == b
    assert 0 <= a <= 99


def test_cohort_bucket_salt_changes_bucket():
    assert cohort_bucket_0_99("t1", "e1", "a") != cohort_bucket_0_99("t1", "e1", "b")


def test_decision_from_rule_score_thresholds():
    assert decision_from_rule_score(10.0) == "allow"
    assert decision_from_rule_score(50.0) == "review"
    assert decision_from_rule_score(80.0) == "deny"


def test_build_canary_cohort_audit_stable():
    a = build_canary_cohort_audit("t1", "e1", salt_version="policy_v1")
    b = build_canary_cohort_audit("t1", "e1", salt_version="policy_v1")
    assert a == b
    assert a["schema_version"] == 1
    assert len(a["cohort_sticky_id"]) == 16
    assert a["cohort_bucket_0_99"] == cohort_bucket_0_99("t1", "e1", "policy_v1")
    assert "experiment_id" not in a


def test_build_canary_cohort_audit_experiment_id():
    d = build_canary_cohort_audit("t", "e", salt_version="v2", experiment_id="exp-a")
    assert d["experiment_id"] == "exp-a"
    assert d["salt_version"] == "v2"


def test_build_policy_routing_audit():
    d = build_policy_routing_audit(
        cohort_bucket=42,
        cohort_salt="policy_v1",
        champion_rule_score=10.0,
        challenger_rule_score=70.0,
        champion_decision="allow",
        challenger_decision="review",
        ml_score=0.5,
    )
    assert d["cohort_bucket_0_99"] == 42
    assert d["decisions_agree"] is False
    assert d["champion_rule_score"] == 10.0
    assert d["challenger_rule_score"] == 70.0
