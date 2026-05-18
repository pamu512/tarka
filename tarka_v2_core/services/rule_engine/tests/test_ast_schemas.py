"""Gate: AST schema nodes construct with strict typing."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from rule_engine.ast_schemas import (  # noqa: E402
    Action,
    AndNode,
    ConditionNode,
    FieldRef,
    LogicalNode,
    Operator,
    OrNode,
    Rule,
    Value,
)


def test_field_ref_amount_and_operator_gt_construct_cleanly() -> None:
    ref = FieldRef(field="amount")
    assert ref.field == "amount"
    op = Operator.GT
    assert op is Operator.GT
    assert op.value == "GT"
    assert str(op) == "GT"
    assert isinstance(op, Operator)


def test_value_literal_construct() -> None:
    v = Value(literal=42.5)
    assert v.literal == 42.5


def test_field_ref_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        FieldRef.model_validate({"field": "unknown_column"})


def test_condition_node_gt_with_string_value_raises_validation_error() -> None:
    with pytest.raises(ValidationError) as excinfo:
        ConditionNode(
            field=FieldRef(field="amount"),
            operator=Operator.GT,
            value="apple",
        )
    assert "GT and LT" in str(excinfo.value) or "string" in str(excinfo.value).lower()


def test_condition_node_ne_with_string_construct_cleanly() -> None:
    node = ConditionNode(
        field=FieldRef(field="country"),
        operator=Operator.NE,
        value="US",
    )
    assert node.operator == Operator.NE


def test_condition_node_gt_with_float_construct_cleanly() -> None:
    node = ConditionNode(
        field=FieldRef(field="amount"),
        operator=Operator.GT,
        value=10.5,
    )
    assert node.operator == Operator.GT
    assert node.value == 10.5


def test_condition_node_contains_non_string_raises() -> None:
    with pytest.raises(ValidationError):
        ConditionNode(
            field=FieldRef(field="metadata"),
            operator=Operator.CONTAINS,
            value=123,
        )


def test_nested_and_or_ast_passes_pydantic_validation() -> None:
    """Gate: AND( OR(amount > 100, amount < 0), EQ(country, \"US\") )."""
    ast = AndNode(
        children=[
            OrNode(
                children=[
                    ConditionNode(
                        field=FieldRef(field="amount"),
                        operator=Operator.GT,
                        value=100,
                    ),
                    ConditionNode(
                        field=FieldRef(field="amount"),
                        operator=Operator.LT,
                        value=0,
                    ),
                ],
            ),
            ConditionNode(
                field=FieldRef(field="country"),
                operator=Operator.EQ,
                value="US",
            ),
        ],
    )
    assert isinstance(ast, AndNode)
    assert len(ast.children) == 2
    assert isinstance(ast.children[0], OrNode)
    assert isinstance(ast.children[1], ConditionNode)
    assert ast.children[1].operator == Operator.EQ
    assert ast.children[1].value == "US"
    inner = ast.children[0]
    assert len(inner.children) == 2
    assert all(isinstance(c, ConditionNode) for c in inner.children)


def test_rule_construct_and_print_model_dump_json(capsys: pytest.CaptureFixture[str]) -> None:
    """Gate: full ``Rule`` in memory serializes via ``model_dump_json()`` and prints cleanly."""
    rule_id = uuid4()
    root = AndNode(
        children=[
            OrNode(
                children=[
                    ConditionNode(
                        field=FieldRef(field="amount"),
                        operator=Operator.GT,
                        value=5000.0,
                    ),
                    ConditionNode(
                        field=FieldRef(field="country"),
                        operator=Operator.EQ,
                        value="XX",
                    ),
                ],
            ),
            ConditionNode(
                field=FieldRef(field="metadata"),
                operator=Operator.CONTAINS,
                value="high_risk",
            ),
        ],
    )
    rule = Rule(
        id=rule_id,
        name="Cross-border high value",
        root_node=root,
        action=Action.FLAG,
        priority=100,
    )
    dumped = rule.model_dump_json()
    print(dumped, end="")
    out = capsys.readouterr().out
    assert out == dumped
    parsed = json.loads(out)
    assert parsed["id"] == str(rule_id)
    assert parsed["name"] == "Cross-border high value"
    assert parsed["action"] == "FLAG"
    assert parsed["priority"] == 100
    assert parsed["root_node"]["children"][0]["children"][0]["operator"] == "GT"


def test_rule_builder_gate_json_round_trips_logical_node() -> None:
    """Gate (Prompt 16–19): ``amount > 500 AND country != 'US'`` as ``AndNode`` JSON."""
    payload = {
        "children": [
            {
                "field": {"field": "amount"},
                "operator": "GT",
                "value": 500,
            },
            {
                "field": {"field": "country"},
                "operator": "NE",
                "value": "US",
            },
        ],
    }
    ta = TypeAdapter(LogicalNode)
    node = ta.validate_python(payload)
    assert isinstance(node, AndNode)
    assert len(node.children) == 2
    c0, c1 = node.children
    assert isinstance(c0, ConditionNode)
    assert isinstance(c1, ConditionNode)
    assert c0.operator == Operator.GT
    assert c1.operator == Operator.NE
    dumped = node.model_dump(mode="json")
    assert dumped == payload
