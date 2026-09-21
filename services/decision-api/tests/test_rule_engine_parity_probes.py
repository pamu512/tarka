"""QA 2026-09-21: Rust-canonical decide semantics (F1–F4, Q1)."""

from __future__ import annotations

import json

import pytest

from decision_api.json_rules import (
    _match_condition,
    _pack_experiment_bucket,
    _pack_should_apply,
)
from decision_api.pack_evaluator import evaluate_packs_python
from decision_api.rule_pack_validation import validate_rule_pack

_ALWAYS_HIT = {
    "id": "always",
    "when": [{"field": "x", "op": "gte", "value": 0}],
    "tags": ["t"],
    "score_delta": 1,
}


def _rust():
    pytest.importorskip("tarka_rule_engine._native")
    import tarka_rule_engine as tre

    return tre


def _hits_python(
    pack: dict, features: dict, *, tenant="acme", entity="user-42"
) -> list[str]:
    out = evaluate_packs_python(
        [pack],
        features,
        [],
        tenant,
        entity,
        "production",
        exclude_shadow=False,
    )
    return list(out["rule_hits"])


def _hits_rust(
    pack: dict, features: dict, *, tenant="acme", entity="user-42"
) -> list[str]:
    tre = _rust()
    raw = tre.evaluate_adhoc_packs_rust(
        json.dumps([pack]),
        json.dumps(features),
        json.dumps([]),
        tenant,
        entity,
        "production",
        None,
    )
    return list(json.loads(raw)["rule_hits"])


@pytest.mark.parametrize(
    ("features", "condition", "want"),
    [
        ({"amount": 10000}, {"field": "amount", "op": "eq", "value": 10000}, True),
        ({"amount": 10000}, {"field": "amount", "op": "eq", "value": 10000.0}, False),
        (
            {"amount": 10000},
            {"field": "amount", "op": "not_eq", "value": 10000.0},
            True,
        ),
        ({"is_new": True}, {"field": "is_new", "op": "eq", "value": 1}, False),
        ({"is_new": True}, {"field": "is_new", "op": "eq", "value": True}, True),
        ({}, {"field": "amount", "op": "eq", "value": None}, False),
        ({"amount": None}, {"field": "amount", "op": "eq", "value": None}, True),
    ],
    ids=[
        "eq_same_int",
        "eq_int_vs_float",
        "not_eq_int_vs_float",
        "eq_true_vs_one",
        "eq_true_vs_true",
        "eq_missing_vs_null",
        "eq_null_vs_null",
    ],
)
def test_f1_eq_is_serde_representation_strict(features, condition, want):
    assert _match_condition(features, condition) is want


@pytest.mark.parametrize(
    ("features", "op", "want"),
    [
        ({"maybe_absent": None}, "exists", True),
        ({"maybe_absent": None}, "not_exists", False),
        ({}, "exists", False),
        ({}, "not_exists", True),
        ({"maybe_absent": 0}, "exists", True),
    ],
    ids=[
        "exists_json_null",
        "not_exists_json_null",
        "exists_missing",
        "not_exists_missing",
        "exists_zero",
    ],
)
def test_f2_exists_is_key_presence(features, op, want):
    assert _match_condition(features, {"field": "maybe_absent", "op": op}) is want


def test_f3_canary_bucket_uses_name_when_source_file_absent():
    pack = {"name": "canary-name", "canary_percent": 50}
    apply, reason = _pack_should_apply(
        pack, "acme", "user-42", evaluation_mode="production"
    )
    named = _pack_experiment_bucket("acme", "user-42", "canary-name")
    fallback = _pack_experiment_bucket("acme", "user-42", "pack")
    assert named != fallback
    assert apply is (named < 50)
    assert reason is None


def test_f4_validate_rule_pack_requires_explicit_version():
    pack = {
        "name": "no-ver",
        "rules": [_ALWAYS_HIT],
        "tag_rules": [],
    }
    errs = validate_rule_pack(pack)
    assert any("version" in e for e in errs)
    pack["version"] = 1
    assert validate_rule_pack(pack) == []


def test_f4_python_evaluate_defaults_missing_version_to_v1():
    pack = {"name": "no-ver", "rules": [_ALWAYS_HIT], "tag_rules": []}
    assert _hits_python(pack, {"x": 1}) == ["always"]


@pytest.mark.parametrize(
    ("features", "pattern", "want"),
    [
        ({"s": "abc"}, "abc", True),
        ({"s": "abc"}, "ABC", True),
        ({"s": "abc"}, "ab*", True),
        ({"x": None}, "null", True),
        ({}, "null", True),
    ],
    ids=[
        "string_unquoted",
        "string_casefold",
        "string_glob_star",
        "json_null",
        "missing_is_json_null_display",
    ],
)
def test_q1_regex_string_subject_is_unquoted(features, pattern, want):
    field = next(iter(features), "s")
    assert (
        _match_condition(features, {"field": field, "op": "regex", "value": pattern})
        is want
    )


@pytest.mark.parametrize(
    ("features", "condition", "want_hit"),
    [
        ({"amount": 10000}, {"field": "amount", "op": "eq", "value": 10000.0}, False),
        ({"maybe_absent": None}, {"field": "maybe_absent", "op": "exists"}, True),
        ({"maybe_absent": None}, {"field": "maybe_absent", "op": "not_exists"}, False),
        ({"s": "abc"}, {"field": "s", "op": "regex", "value": "abc"}, True),
    ],
    ids=["f1_eq_int_float", "f2_exists_null", "f2_not_exists_null", "q1_regex_abc"],
)
def test_dual_engine_flat_when_matches(features, condition, want_hit):
    pack = {
        "version": 1,
        "name": "probe",
        "rules": [
            {
                "id": "probe",
                "when": [condition],
                "tags": [],
                "score_delta": 1,
            }
        ],
        "tag_rules": [],
    }
    py = "probe" in _hits_python(pack, features)
    rust = "probe" in _hits_rust(pack, features)
    assert py is want_hit
    assert rust is want_hit


def test_f3_dual_engine_canary_name_key_agrees():
    pack = {
        "version": 1,
        "name": "canary-name",
        "canary_percent": 50,
        "rules": [_ALWAYS_HIT],
        "tag_rules": [],
    }
    py = _hits_python(pack, {"x": 1})
    rust = _hits_rust(pack, {"x": 1})
    assert py == rust == ["always"]


def test_f4_dual_engine_missing_version_still_evaluates():
    pack = {"name": "no-ver", "rules": [_ALWAYS_HIT], "tag_rules": []}
    py = _hits_python(pack, {"x": 1})
    rust = _hits_rust(pack, {"x": 1})
    assert py == rust == ["always"]
