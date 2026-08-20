"""Degrade-skip score delta: runtime-unavailable hops heat the entity.

Proves:
 1. runtime unavailable → score increases (showing-signs)
 2. unconfigured / disabled / operator posture → zero delta
 3. many unavailable tags → capped at 15
 4. skip does NOT force deny unless fail-closed is on
 5. fail-closed opt-in still forces deny
"""

from decision_api.decision_outcome import force_deny_from_degrade_tags
from decision_api.evaluate.score import (
    _DEGRADE_SKIP_CAP,
    _DEGRADE_SKIP_SCORE,
    blend_scores,
    degrade_skip_score_delta,
)


# -- 1. Runtime unavailable adds score --


def test_single_unavailable_tag_adds_delta():
    assert degrade_skip_score_delta(["graph:unavailable"]) == 5.0


def test_multiple_unavailable_tags_sum():
    tags = ["graph:unavailable", "ml:unavailable", "lists:unavailable"]
    assert degrade_skip_score_delta(tags) == 15.0


def test_stale_skipped_scores():
    assert degrade_skip_score_delta(["graph:stale_skipped"]) == 5.0


def test_base_score_increases_with_skip_delta():
    """Simulates pipeline base_score: 10 + rule_delta + degrade_delta."""
    degrade_tags = ["ml:unavailable", "opa:unavailable"]
    degrade_delta = degrade_skip_score_delta(degrade_tags)
    final = blend_scores(10.0 + degrade_delta, None)
    assert final == 20.0  # 10 base + 5 + 5
    assert final > 10.0


# -- 2. Operator posture tags do NOT score --


def test_unconfigured_tags_zero_delta():
    posture = [
        "graph:unconfigured",
        "enrichment:unconfigured",
        "ml:unconfigured",
        "opa:unconfigured",
        "calibration:unconfigured",
        "counter:unconfigured",
        "location:unconfigured",
    ]
    assert degrade_skip_score_delta(posture) == 0.0


def test_disabled_tags_zero_delta():
    assert degrade_skip_score_delta(["ml:disabled"]) == 0.0


def test_disabled_by_tenant_zero_delta():
    tenant_disabled = [
        "lists:disabled_by_tenant",
        "graph:disabled_by_tenant",
        "enrichment:disabled_by_tenant",
        "ml:disabled_by_tenant",
        "opa:disabled_by_tenant",
    ]
    assert degrade_skip_score_delta(tenant_disabled) == 0.0


def test_load_shedding_not_scored():
    assert degrade_skip_score_delta(["load_shedding:active"]) == 0.0


def test_counter_fallback_not_scored():
    assert degrade_skip_score_delta(["counter:fallback_local_agg"]) == 0.0


def test_consortium_not_scored():
    assert degrade_skip_score_delta(["consortium:unavailable"]) == 0.0


def test_lite_desk_posture_zero_delta():
    """Lite desk: graph unset, ML disabled, OPA unset, calibration unset → zero."""
    lite = [
        "graph:unconfigured",
        "ml:disabled",
        "opa:unconfigured",
        "calibration:unconfigured",
    ]
    assert degrade_skip_score_delta(lite) == 0.0


# -- 3. Cap at 15 --


def test_many_unavailable_capped():
    all_tags = list(_DEGRADE_SKIP_SCORE.keys())
    assert len(all_tags) > 3  # more than cap / 5
    assert degrade_skip_score_delta(all_tags) == _DEGRADE_SKIP_CAP


def test_cap_value_prevents_review():
    """10 base + 15 cap = 25, well below review threshold (50)."""
    final = blend_scores(10.0 + _DEGRADE_SKIP_CAP, None)
    assert final < 50.0


def test_no_degrade_tags_zero_delta():
    assert degrade_skip_score_delta([]) == 0.0


# -- 4. Skip does NOT force deny --


def test_skip_tags_do_not_force_deny():
    for tag in _DEGRADE_SKIP_SCORE:
        assert not force_deny_from_degrade_tags([tag]), f"{tag} must not force deny"


# -- 5. Fail-closed opt-in still forces deny --


def test_fail_closed_catalog_forces_deny():
    assert force_deny_from_degrade_tags(["feature:catalog_fail_closed"])


def test_fail_closed_graph_stale_forces_deny():
    assert force_deny_from_degrade_tags(["graph:stale_fail_closed"])


def test_fail_closed_with_skip_tags_still_forces_deny():
    tags = ["graph:unavailable", "feature:catalog_fail_closed", "ml:unavailable"]
    assert force_deny_from_degrade_tags(tags)
