"""Unit tests for manifest_compare_logic (no HTTP)."""

from __future__ import annotations

from decision_api.manifest_compare_logic import (
    build_full_manifest_comparison,
    deep_diff_structural,
    find_divergence_explanation,
)


def test_deep_diff_nested_mismatch() -> None:
    a = {"x": 1, "nested": {"k": [1, 2]}}
    b = {"x": 1, "nested": {"k": [1, 3]}}
    d = deep_diff_structural(a, b)
    assert d["match"] is False
    assert d["kind"] == "object"


def test_find_divergence_boolean_result() -> None:
    sa = [
        {
            "rule_id": "r1",
            "logic_operator": "",
            "operands": [],
            "result": True,
            "state_snapshot": {},
            "state_snapshot_decoded": {},
        },
        {
            "rule_id": "r2",
            "logic_operator": "",
            "operands": [],
            "result": True,
            "state_snapshot": {},
            "state_snapshot_decoded": {},
        },
    ]
    sb = [
        {
            "rule_id": "r1",
            "logic_operator": "",
            "operands": [],
            "result": True,
            "state_snapshot": {},
            "state_snapshot_decoded": {},
        },
        {
            "rule_id": "r2",
            "logic_operator": "",
            "operands": [],
            "result": False,
            "state_snapshot": {},
            "state_snapshot_decoded": {},
        },
    ]
    out = find_divergence_explanation(sa, sb, final_decision_a=True, final_decision_b=False)
    assert out["first_divergence_step_index"] == 1
    assert out["divergence_category"] == "rule_boolean_result"
    assert out["culprit_rule_id"] == "r2"


def test_find_divergence_length() -> None:
    sa = [
        {
            "rule_id": "a",
            "logic_operator": "",
            "operands": [],
            "result": True,
            "state_snapshot": {},
            "state_snapshot_decoded": {},
        }
    ]
    sb = sa + [
        {
            "rule_id": "extra",
            "logic_operator": "",
            "operands": [],
            "result": False,
            "state_snapshot": {},
            "state_snapshot_decoded": {},
        }
    ]
    out = find_divergence_explanation(sa, sb, final_decision_a=False, final_decision_b=False)
    assert out["first_divergence_step_index"] == 1
    assert out["divergence_category"] == "execution_path_length"
    assert out["culprit_rule_id"] == "extra"
    assert out["culprit_manifest_side"] == "manifest_b"


def test_build_full_comparison_payload() -> None:
    bundle_a = {
        "signals": {"s": "1"},
        "engine_version": "v1",
        "timestamp_ns": 1,
        "final_decision": 1,
        "total_execution_time_us": 10,
    }
    bundle_b = dict(bundle_a)
    bundle_b["signals"] = {"s": "2"}
    steps_a = [
        {
            "rule_id": "r",
            "logic_operator": "",
            "operands": [],
            "result": True,
            "state_snapshot": {"k": "1"},
            "state_snapshot_decoded": {"k": 1},
        }
    ]
    steps_b = [
        {
            "rule_id": "r",
            "logic_operator": "",
            "operands": [],
            "result": True,
            "state_snapshot": {"k": "2"},
            "state_snapshot_decoded": {"k": 2},
        }
    ]
    payload = build_full_manifest_comparison(
        manifest_id_a="a",
        manifest_id_b="b",
        bundle_a=bundle_a,
        bundle_b=bundle_b,
        steps_a=steps_a,
        steps_b=steps_b,
        final_a=True,
        final_b=True,
    )
    assert payload["path_lengths"]["manifest_a"] == 1
    assert payload["metadata_diff"]["signals"]["match"] is False
    assert payload["divergence"]["divergence_category"] == "intermediate_state"
