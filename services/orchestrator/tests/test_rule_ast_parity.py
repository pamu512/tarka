"""S0 parity harness: Python shadow-test AST vs the Rust strict JSON-AST twin.

Pins the prune plan's (v7 item 2.1) migration precondition: for every tree the
``/v1/rules/shadow-test`` route can legally build, ``rule_ast_bridge`` (the mapping)
plus ``tarka_rule_engine.evaluate_json_ast_strict`` (the twin) must agree with
``rule_engine.evaluator.evaluate_node``.

Operator table under test: EQ->eq, NE->not_eq, GT->gt, LT->lt, CONTAINS->contains.
The parser stores ``op`` as written (json_ast.rs:222-226), so the bridge's table is
the only translation point; nothing normalizes operators.

One divergence is pinned explicitly at the bottom (CONTAINS over structured LHS and
separator-spanning substrings); it is documented in ``rule_ast_bridge`` and outside
the shadow-test contract.
"""

from __future__ import annotations

import sys
import uuid as uuid_lib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

_SRC_ORCH = Path(__file__).resolve().parents[1]
if str(_SRC_ORCH) not in sys.path:
    sys.path.insert(0, str(_SRC_ORCH))

from rule_ast_bridge import (  # noqa: E402
    RuleAstBridgeError,
    evaluate_shadow_tree_via_rust,
    logical_tree_to_json_ast,
    transaction_feature_map,
)
from tarka_shared.ast_schemas import (  # noqa: E402
    AndNode,
    ConditionNode,
    FieldRef,
    Operator,
    OrNode,
)

from evaluator import evaluate_node  # noqa: E402
from ingestor.manifest_schema import TransactionSchema  # noqa: E402

_T0 = datetime(2026, 11, 17, 12, 0, 0, tzinfo=timezone.utc)
_T1 = datetime(2026, 11, 17, 13, 30, 0, tzinfo=timezone.utc)
_E0 = "3f2a8c1e-9b4d-4c6a-8e2f-111111111111"
_E1 = "3f2a8c1e-9b4d-4c6a-8e2f-222222222222"


def _tx(
    *,
    entity_id: str = _E0,
    amount: float = 250.0,
    timestamp: datetime = _T0,
    metadata: dict[str, Any] | None = None,
    country: str | None = "DE",
) -> TransactionSchema:
    return TransactionSchema(
        entity_id=uuid_lib.UUID(entity_id),
        amount=amount,
        timestamp=timestamp,
        metadata=metadata if metadata is not None else {"channel": "web", "device": "ios"},
        country=country,
    )


def _cond(field: str, op: Operator, value: Any) -> ConditionNode:
    return ConditionNode(field=FieldRef(field=field), operator=op, value=value)


def _assert_parity(root, tx: TransactionSchema, graph: dict[str, Any] | None = None) -> None:
    py = evaluate_node(root, tx, graph)
    rust = evaluate_shadow_tree_via_rust(root, tx, graph)
    assert py is rust or py == rust, f"parity broken: python={py} rust={rust}"


@pytest.mark.parametrize(
    ("field", "op", "value", "tx"),
    [
        # amount: numeric rhs in every legal literal form
        ("amount", Operator.EQ, 250.0, _tx(amount=250.0)),
        ("amount", Operator.EQ, 250, _tx(amount=250.0)),
        ("amount", Operator.NE, 100, _tx(amount=250.0)),
        ("amount", Operator.GT, 100, _tx(amount=250.0)),
        ("amount", Operator.GT, 250, _tx(amount=250.0)),
        ("amount", Operator.LT, 251.5, _tx(amount=250.0)),
        ("amount", Operator.LT, 250.0, _tx(amount=250.0)),
        # string lhs: eq / ne / contains
        ("country", Operator.EQ, "DE", _tx(country="DE")),
        ("country", Operator.EQ, None, _tx(country=None)),
        ("country", Operator.NE, "US", _tx(country="DE")),
        ("country", Operator.NE, None, _tx(country="DE")),
        ("country", Operator.CONTAINS, "D", _tx(country="DE")),
        ("country", Operator.CONTAINS, "ZZ", _tx(country="DE")),
    ],
)
def test_scalar_conditions(field: str, op: Operator, value: Any, tx: TransactionSchema) -> None:
    _assert_parity(_cond(field, op, value), tx)


def test_entity_id_eq_canonical_wire_form() -> None:
    tx = _tx(entity_id=_E0)
    _assert_parity(_cond("entity_id", Operator.EQ, _E0), tx)
    _assert_parity(_cond("entity_id", Operator.NE, _E1), tx)


def test_timestamp_eq_and_ordering() -> None:
    tx = _tx(timestamp=_T1)
    # wire-string rhs for EQ (the form callers send); Python coerces via _normalize_eq_rhs
    _assert_parity(_cond("timestamp", Operator.EQ, _T1.isoformat()), tx)
    _assert_parity(_cond("timestamp", Operator.NE, _T0.isoformat()), tx)
    # datetime rhs (validated literal)
    _assert_parity(_cond("timestamp", Operator.GT, _T0), tx)
    _assert_parity(_cond("timestamp", Operator.LT, _T0), tx)
    # unparseable string rhs for EQ: Python compares datetime == str -> False
    _assert_parity(_cond("timestamp", Operator.EQ, "not-a-date"), tx)


def test_timestamp_string_rhs_rejected_for_gt_lt() -> None:
    """ConditionNode's validator rejects string literals for GT/LT.

    This is what keeps the mapping closed: ordering comparisons only ever see
    datetime or numeric literals, which map to epoch/float.
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="numeric or datetime"):
        _cond("timestamp", Operator.GT, _T0.isoformat())
    with pytest.raises(ValidationError, match="numeric or datetime"):
        _cond("timestamp", Operator.LT, _T0.isoformat())


def test_metadata_eq_and_contains_token() -> None:
    tx = _tx(metadata={"channel": "web", "device": "ios"})
    _assert_parity(_cond("metadata", Operator.EQ, {"channel": "web", "device": "ios"}), tx)
    _assert_parity(_cond("metadata", Operator.NE, {"channel": "app"}), tx)
    # separator-insensitive substring: matches both serializations
    _assert_parity(_cond("metadata", Operator.CONTAINS, '"device"'), tx)
    _assert_parity(_cond("metadata", Operator.CONTAINS, "ios"), tx)
    _assert_parity(_cond("metadata", Operator.CONTAINS, '"android"'), tx)


def test_graph_count_with_and_without_context() -> None:
    tx = _tx()
    _assert_parity(_cond("graph_linked_to_blocked_count", Operator.GT, 0), tx)
    _assert_parity(_cond("graph_linked_to_blocked_count", Operator.GT, 0), tx, {"graph_linked_to_blocked_count": 3})
    _assert_parity(_cond("graph_linked_to_blocked_count", Operator.EQ, 3), tx, {"graph_linked_to_blocked_count": "3"})
    _assert_parity(_cond("graph_linked_to_blocked_count", Operator.LT, 5), tx, {"graph_linked_to_blocked_count": 3})


def test_nested_and_or_trees() -> None:
    tx = _tx(amount=900.0, country="US")
    tree = AndNode(
        children=[
            _cond("amount", Operator.GT, 500),
            OrNode(
                children=[
                    _cond("country", Operator.EQ, "US"),
                    _cond("country", Operator.EQ, "CA"),
                ],
            ),
        ],
    )
    _assert_parity(tree, tx)
    _assert_parity(
        OrNode(children=[tree, _cond("country", Operator.EQ, "ZZ")]),
        tx,
    )
    _assert_parity(
        AndNode(children=[_cond("amount", Operator.LT, 100), _cond("country", Operator.EQ, "US")]),
        tx,
    )


def test_mapping_rejects_unmappable_operator() -> None:
    import rule_ast_bridge

    original = rule_ast_bridge._CONDITION_OPERATOR_WIRE
    rule_ast_bridge._CONDITION_OPERATOR_WIRE = {
        Operator.EQ: "eq",
    }  # simulate a future enum member without a twin entry
    try:
        with pytest.raises(RuleAstBridgeError):
            logical_tree_to_json_ast(_cond("country", Operator.NE, "US"))
    finally:
        rule_ast_bridge._CONDITION_OPERATOR_WIRE = original


def test_feature_map_covers_closed_field_set() -> None:
    tx = _tx()
    features = transaction_feature_map(tx, {"graph_linked_to_blocked_count": 2})
    assert set(features) == {
        "entity_id",
        "amount",
        "timestamp",
        "metadata",
        "country",
        "graph_linked_to_blocked_count",
    }
    assert features["entity_id"] == _E0
    assert features["amount"] == 250.0
    assert isinstance(features["timestamp"], float)
    assert features["graph_linked_to_blocked_count"] == 2.0


def test_known_divergence_contains_separator_spanning_substring() -> None:
    """Documented boundary, not a parity claim.

    Python serializes a structured LHS with ``", "`` / ``": "`` separators; the engine
    serializes compactly. A substring that spans a separator therefore matches on one
    side only. The shadow-test contract promises separator-insensitive substrings
    (quoted key tokens, plain words); anything else is out of contract.
    """
    tx = _tx(metadata={"channel": "web"})
    root = _cond("metadata", Operator.CONTAINS, '"channel": "web"')
    py = evaluate_node(root, tx)
    rust = evaluate_shadow_tree_via_rust(root, tx)
    assert py is True
    assert rust is False
