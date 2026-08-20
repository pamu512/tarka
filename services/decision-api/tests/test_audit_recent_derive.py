from decision_api.audit_recent_derive import derive_rule_result


def test_derive_rule_result_explicit_and_shadow_tags():
    assert (
        derive_rule_result("allow", [], {"rule_result": "SHADOW_REVIEW"})
        == "SHADOW_REVIEW"
    )
    assert derive_rule_result("allow", ["shadow_review"], {}) == "SHADOW_REVIEW"
    pr = {
        "decisions_agree": False,
        "champion_decision": "allow",
        "challenger_decision": "review",
    }
    assert derive_rule_result("allow", [], {"policy_routing": pr}) == "SHADOW_REVIEW"
    assert derive_rule_result("deny", [], {}) == "DENY"
    assert derive_rule_result("review", [], {}) == "REVIEW"


def test_deny_with_fallback_reason_becomes_review():
    """A deny under degraded signals (skipped check) should surface as REVIEW, not DENY."""
    assert derive_rule_result("deny", [], {"fallback_reason": "circuit_ml"}) == "REVIEW"
    assert (
        derive_rule_result("deny", [], {"fallback_reason": "circuit_ml; circuit_graph"})
        == "REVIEW"
    )


def test_deny_without_fallback_reason_stays_deny():
    """A clean deny (no degraded path) remains DENY."""
    assert derive_rule_result("deny", [], {}) == "DENY"
    assert derive_rule_result("deny", [], {"fallback_reason": None}) == "DENY"
    assert derive_rule_result("deny", [], {"fallback_reason": ""}) == "DENY"


def test_allow_with_fallback_reason_stays_allow():
    """Only deny is re-mapped; allow under degraded signals stays ALLOW."""
    assert derive_rule_result("allow", [], {"fallback_reason": "circuit_ml"}) == "ALLOW"
