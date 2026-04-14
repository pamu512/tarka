"""Challenge policy templates (Epic D)."""

import pytest
from decision_api.challenge_policy import (
    apply_challenge_policy,
    load_challenge_policies,
)


@pytest.fixture(autouse=True)
def _reload_policies(monkeypatch):
    """Use repo rules/challenge_policies relative to default ./rules when cwd is decision-api."""
    monkeypatch.setenv("CHALLENGE_POLICY_DEFAULT", "default_v1")
    load_challenge_policies(force=True)
    yield
    load_challenge_policies(force=True)


def test_default_v1_passthrough_engine():
    inf = {"confidence_tier": "medium"}
    base = "manual_review"
    out, meta = apply_challenge_policy("default_v1", base, "review", inf, [], {})
    assert out == base
    assert meta.get("matched_rule_id") is None
    assert meta.get("policy_id") == "default_v1"


def test_strict_review_forces_manual_for_low_tier_review():
    """Engine gives step_up_mfa for review+low; strict template forces manual_review."""
    inf = {"confidence_tier": "low"}
    base = "step_up_mfa"
    out, meta = apply_challenge_policy(
        "strict_review_v1",
        base,
        "review",
        inf,
        [],
        {},
    )
    assert out == "manual_review"
    assert meta.get("matched_rule_id") == "review_manual_queue"


def test_payments_high_value_allow():
    inf = {"confidence_tier": "high"}
    base = None
    out, meta = apply_challenge_policy(
        "payments_high_value_v1",
        base,
        "allow",
        inf,
        [],
        {"amount": 6000},
    )
    assert out == "step_up_attestation"
    assert meta.get("matched_rule_id") == "high_value_allow"


def test_matches_has_tag():
    from decision_api.challenge_policy import _matches_when

    assert _matches_when(
        {"has_tag": "ingress:replay"},
        "allow",
        {},
        ["ingress:replay_payload"],
        {},
    )
    assert not _matches_when(
        {"has_tag": "ingress:replay"},
        "allow",
        {},
        ["other"],
        {},
    )
