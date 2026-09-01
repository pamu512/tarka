"""Brain-wire CI witness: FP leftover extras drop scout pack publish."""

from __future__ import annotations

from decision_api.brain_wire import brain_wire_verdict


def test_brain_wire_ci_witness_fp_extras_drop_scout_pack() -> None:
    """Stretch Observe/AI honesty: FP-over-cap must refuse publish (no 'AI decided')."""
    verdict = brain_wire_verdict(
        {
            "blockers": ["leftover_extras_fp_over_cap"],
            "underpowered": False,
            "labeled_extras": 5,
            "extra_tp": 0,
            "extra_fp": 5,
        },
        {"rules": []},
        proposed_rule_ids=["scout_r1"],
        fp_cap=0.4,
    )
    assert verdict["publish_allowed"] is False
    assert verdict["reason"] == "leftover_extras_fp_over_cap"
    assert verdict["should_kill"] is True
