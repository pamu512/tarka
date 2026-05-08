"""Unit tests for manifest step matching (no network)."""

from __future__ import annotations

from tarka_test.manifest_match import (
    extract_manifest_steps,
    match_expected_steps,
    normalize_keys,
    step_matches,
)


def test_step_matches_subset() -> None:
    actual = {"rule_id": "r1", "result": True, "operands": ["a", "b"]}
    assert step_matches({"rule_id": "r1"}, actual)
    assert step_matches({"result": True}, actual)
    assert not step_matches({"rule_id": "r2"}, actual)


def test_ordered_matching() -> None:
    steps = [
        {"step": "list", "status": "ok"},
        {"step": "rules", "status": "ok"},
    ]
    ok, msg = match_expected_steps(
        steps,
        [{"step": "list"}, {"step": "rules"}],
        ordered=True,
    )
    assert ok, msg


def test_ordered_fails_wrong_order() -> None:
    steps = [
        {"step": "rules"},
        {"step": "list"},
    ]
    ok, msg = match_expected_steps(
        steps,
        [{"step": "list"}, {"step": "rules"}],
        ordered=True,
    )
    assert not ok


def test_extract_manifest_steps_dict() -> None:
    m = {
        "trace": {
            "steps": [
                {"ruleId": "x", "result": True},
            ]
        }
    }
    steps = extract_manifest_steps(m)
    assert len(steps) == 1
    assert steps[0]["rule_id"] == "x"


def test_normalize_keys_camel() -> None:
    assert normalize_keys({"ruleId": "z"}) == {"rule_id": "z"}
