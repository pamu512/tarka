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
from decision_api.pack_evaluator import _rule_when_matches  # noqa: E402


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
    compiled = _compile_to_json_rules(pack)
    rule = compiled["rules"][0]
    assert "when_ast" in rule
    assert "when" not in rule
    assert _rule_when_matches(rule, {"a": True, "b": False}, "t", "e") is True
    assert _rule_when_matches(rule, {"a": False, "b": False}, "t", "e") is False


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
    compiled = _compile_to_json_rules(pack)
    rule = compiled["rules"][0]
    assert "when" in rule
    assert _rule_when_matches(rule, {"a": True, "b": False}, "t", "e") is False
    assert _rule_when_matches(rule, {"a": True, "b": True}, "t", "e") is True
