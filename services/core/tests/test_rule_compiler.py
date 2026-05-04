"""Unit tests for JSON visual AST → Rego transpilation."""

import pytest

from tarka_core.rule_compiler import TranspilationError, transpile_visual_pack, transpile_visual_rule


def test_transpile_simple_eq() -> None:
    rid, expr = transpile_visual_rule(
        {
            "id": "r_eq",
            "all_of": [{"field": "country", "op": "==", "value": "US"}],
            "any_of": [],
        }
    )
    assert rid == "r_eq"
    assert expr == 'input.country == "US"'


def test_transpile_gt_lt_combined_with_or() -> None:
    rid, expr = transpile_visual_rule(
        {
            "id": "r_cmp",
            "all_of": [{"field": "amount", "op": ">", "value": 100}],
            "any_of": [
                {"field": "amount", "op": "<", "value": 500},
                {"field": "tier", "op": "==", "value": "trusted"},
            ],
        }
    )
    assert rid == "r_cmp"
    assert (
        expr
        == '(input.amount > 100 and (input.amount < 500 or input.tier == "trusted"))'
    )


def test_transpile_in_not_in_nested() -> None:
    rid, expr = transpile_visual_rule(
        {
            "id": "r_sets",
            "all_of": [
                {"field": "region", "op": "IN", "value": ["US", "CA"]},
                {"field": "status", "op": "not in", "value": ["blocked", "frozen"]},
            ],
            "any_of": [],
        }
    )
    assert rid == "r_sets"
    assert (
        expr
        == '(input.region in {"US", "CA"} and not (input.status in {"blocked", "frozen"}))'
    )


def test_transpile_deep_nested_and_or() -> None:
    pack = {
        "name": "deep",
        "rules": [
            {
                "id": "r_deep",
                "all_of": [],
                "any_of": [
                    {
                        "all_of": [
                            {"field": "a", "op": "==", "value": 1},
                            {
                                "any_of": [
                                    {"field": "b", "op": ">", "value": 0},
                                    {"field": "c", "op": "<", "value": 0},
                                ]
                            },
                        ]
                    },
                    {"field": "d", "op": "==", "value": True},
                ],
            }
        ],
    }
    expected = """package tarka.visual

import rego.v1

rules contains "r_deep" if {
    ((input.a == 1 and (input.b > 0 or input.c < 0)) or input.d == true)
}
"""
    assert transpile_visual_pack(pack) == expected


def test_transpile_pack_two_rules_ordering() -> None:
    pack = {
        "name": "p1",
        "rules": [
            {"id": "z_last", "all_of": [{"field": "x", "op": "eq", "value": 1}], "any_of": []},
            {"id": "a_first", "all_of": [{"field": "y", "op": "ne", "value": 2}], "any_of": []},
        ],
    }
    out = transpile_visual_pack(pack)
    assert out.index('rules contains "z_last"') < out.index('rules contains "a_first"')


def test_transpile_rejects_macro() -> None:
    with pytest.raises(TranspilationError, match="unsupported AST keys"):
        transpile_visual_rule(
            {
                "id": "bad",
                "all_of": [{"field": "x", "op": "eq", "value": 1, "macro": "m"}],
                "any_of": [],
            }
        )


def test_transpile_rejects_contains_operator() -> None:
    with pytest.raises(TranspilationError, match="contains"):
        transpile_visual_rule(
            {
                "id": "bad2",
                "all_of": [{"field": "x", "op": "contains", "value": "a"}],
                "any_of": [],
            }
        )


def test_transpile_rejects_mixed_in_set() -> None:
    with pytest.raises(TranspilationError, match="all strings or all numbers"):
        transpile_visual_rule(
            {
                "id": "bad3",
                "all_of": [{"field": "x", "op": "in", "value": ["a", 1]}],
                "any_of": [],
            }
        )


def test_transpile_prefixed_input_field() -> None:
    rid, expr = transpile_visual_rule(
        {
            "id": "pref",
            "all_of": [{"field": "input.foo.bar", "op": "==", "value": 3}],
            "any_of": [],
        }
    )
    assert rid == "pref"
    assert expr == "input.foo.bar == 3"
