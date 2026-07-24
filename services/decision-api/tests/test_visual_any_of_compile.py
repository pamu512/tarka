"""Phase 0: visual any_of must compile as OR, not AND."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from decision_api.rule_compiler_api import (  # noqa: E402
    VisualAstLeaf,
    VisualAstPack,
    VisualAstRule,
    _compile_to_json_rules,
)


def _eval_ast(node: dict, features: dict) -> bool:
    typ = node.get("type")
    if typ == "condition":
        op = node.get("op")
        field = node.get("field")
        actual = features.get(field)
        if op == "is_true":
            return actual is True
        if op == "eq":
            return actual == node.get("value")
        return False
    children = node.get("children") or []
    if typ == "and":
        return all(_eval_ast(c, features) for c in children)
    if typ == "or":
        return any(_eval_ast(c, features) for c in children)
    return False


def _matches(rule: dict, features: dict) -> bool:
    if "when_ast" in rule:
        return _eval_ast(rule["when_ast"], features)
    when = rule.get("when") or []
    return all(
        (features.get(c["field"]) is True)
        if c.get("op") == "is_true"
        else features.get(c["field"]) == c.get("value")
        for c in when
    )


def test_any_of_true_false_matches() -> None:
    pack = VisualAstPack(
        name="any_of_gate",
        rules=[
            VisualAstRule(
                id="any_demo",
                any_of=[
                    VisualAstLeaf(field="a", op="is_true", value=True),
                    VisualAstLeaf(field="b", op="is_true", value=True),
                ],
                tags=["HIT"],
                score_delta=10,
            )
        ],
    )
    rule = _compile_to_json_rules(pack)["rules"][0]
    assert "when_ast" in rule
    assert "when" not in rule
    assert _matches(rule, {"a": True, "b": False}) is True
    assert _matches(rule, {"a": False, "b": False}) is False


def test_all_of_true_false_does_not_match() -> None:
    pack = VisualAstPack(
        name="all_of_gate",
        rules=[
            VisualAstRule(
                id="all_demo",
                all_of=[
                    VisualAstLeaf(field="a", op="is_true", value=True),
                    VisualAstLeaf(field="b", op="is_true", value=True),
                ],
                tags=["HIT"],
                score_delta=10,
            )
        ],
    )
    rule = _compile_to_json_rules(pack)["rules"][0]
    assert "when" in rule
    assert _matches(rule, {"a": True, "b": False}) is False
    assert _matches(rule, {"a": True, "b": True}) is True
