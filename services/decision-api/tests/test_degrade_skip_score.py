"""Degrade-skip score delta: skipped/unavailable hops heat the entity.

Proves:
 1. skip → score increases (showing-signs)
 2. skip does NOT force deny unless fail-closed is on
 3. available hop does not get the skip delta
 4. fail-closed opt-in still forces deny
"""

from decision_api.decision_outcome import force_deny_from_degrade_tags
from decision_api.evaluate.score import (
    _DEGRADE_SKIP_SCORE,
    blend_scores,
    degrade_skip_score_delta,
)


# -- 1. Skip / unavailable adds score --

def test_single_unavailable_tag_adds_delta():
    assert degrade_skip_score_delta(["graph:unavailable"]) == 5.0


def test_multiple_unavailable_tags_sum():
    tags = ["graph:unavailable", "ml:disabled", "lists:unavailable"]
    assert degrade_skip_score_delta(tags) == 15.0


def test_all_known_skip_tags_contribute():
    all_tags = list(_DEGRADE_SKIP_SCORE.keys())
    expected = sum(_DEGRADE_SKIP_SCORE.values())
    assert degrade_skip_score_delta(all_tags) == expected
    assert expected > 0


def test_base_score_increases_with_skip_delta():
    """Simulates pipeline base_score assembly: 10 + rule_delta + degrade_delta."""
    rule_delta = 0.0
    degrade_tags = ["ml:unavailable", "opa:unconfigured"]
    degrade_delta = degrade_skip_score_delta(degrade_tags)
    base_score = 10.0 + rule_delta + degrade_delta
    final = blend_scores(base_score, None)
    assert final == 20.0  # 10 base + 5 + 5
    assert final > 10.0  # hotter than clean baseline


# -- 2. Skip is NOT a forced deny --

def test_skip_tags_do_not_force_deny():
    for tag in _DEGRADE_SKIP_SCORE:
        assert not force_deny_from_degrade_tags([tag]), (
            f"{tag} must not force deny"
        )


def test_skip_score_stays_below_deny_threshold():
    """Even with many skipped hops, score alone shouldn't hit 80 (deny) from base 10."""
    tags = ["graph:unavailable", "ml:disabled", "lists:unavailable",
            "opa:unconfigured", "location:unavailable"]
    degrade_delta = degrade_skip_score_delta(tags)
    final = blend_scores(10.0 + degrade_delta, None)
    assert final < 80.0  # well below deny threshold


# -- 3. Available hop produces zero skip delta --

def test_no_degrade_tags_zero_delta():
    assert degrade_skip_score_delta([]) == 0.0


def test_unrecognised_tag_ignored():
    assert degrade_skip_score_delta(["custom:something"]) == 0.0


def test_load_shedding_not_scored():
    """load_shedding:active is system-level, not a hop skip."""
    assert degrade_skip_score_delta(["load_shedding:active"]) == 0.0


def test_consortium_not_scored():
    """consortium:unavailable is cross-tenant, not first-party."""
    assert degrade_skip_score_delta(["consortium:unavailable"]) == 0.0


def test_fail_closed_tags_not_in_skip_map():
    """Fail-closed tags already force deny; they don't need a skip delta."""
    assert degrade_skip_score_delta(["feature:catalog_fail_closed"]) == 0.0
    assert degrade_skip_score_delta(["graph:stale_fail_closed"]) == 0.0


# -- 4. Fail-closed opt-in still forces deny --

def test_fail_closed_catalog_forces_deny():
    assert force_deny_from_degrade_tags(["feature:catalog_fail_closed"])


def test_fail_closed_graph_stale_forces_deny():
    assert force_deny_from_degrade_tags(["graph:stale_fail_closed"])


def test_fail_closed_with_skip_tags_still_forces_deny():
    """Fail-closed overrides regardless of skip tags present."""
    tags = ["graph:unavailable", "feature:catalog_fail_closed", "ml:disabled"]
    assert force_deny_from_degrade_tags(tags)
