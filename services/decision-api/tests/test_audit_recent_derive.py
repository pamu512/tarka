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
