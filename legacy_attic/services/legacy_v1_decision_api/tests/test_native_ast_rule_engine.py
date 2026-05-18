"""Native Python JSON AST engine: Pydantic validation, evaluation, fail-closed pack rules, and HTTP."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import TypeAdapter, ValidationError

from decision_api.ast_evaluator import evaluate_json_ast
from decision_api.ast_models import (
    MAX_AST_DEPTH,
    MAX_AST_NODES,
    EvaluateAstRequest,
    JsonAstNode,
    ast_node_count,
)
from decision_api.json_rules import evaluate_json_rules


def _nest_and_chain(depth: int) -> dict:
    cur: dict = {"type": "condition", "op": "eq", "field": "k", "value": 1}
    for _ in range(depth - 1):
        cur = {"type": "and", "children": [cur]}
    return cur


def _binary_or_tree(depth: int) -> dict:
    """Full binary tree of OR nodes; depth=8 yields > ``MAX_AST_NODES`` leaves + branches."""
    if depth <= 0:
        return {"type": "condition", "op": "eq", "field": "x", "value": 1}
    return {
        "type": "or",
        "children": [
            _binary_or_tree(depth - 1),
            _binary_or_tree(depth - 1),
        ],
    }


def test_deep_and_chain_all_conditions_true_twelve_levels() -> None:
    """Deep left-nested AND: every leaf is ``k == 1``; features satisfy all levels."""
    raw = _nest_and_chain(12)
    req = EvaluateAstRequest.model_validate({"features": {"k": 1}, "ast": raw})
    assert evaluate_json_ast(req.ast, req.features) is True


def test_deep_and_chain_one_false_short_circuits_logically() -> None:
    """Nested AND fails closed when an inner branch requires a false value."""
    inner = {"type": "condition", "op": "eq", "field": "a", "value": 1}
    mid = {
        "type": "and",
        "children": [
            inner,
            {"type": "condition", "op": "eq", "field": "b", "value": 2},
        ],
    }
    root = {
        "type": "and",
        "children": [mid, {"type": "condition", "op": "eq", "field": "c", "value": 3}],
    }
    req = EvaluateAstRequest.model_validate(
        {"features": {"a": 1, "b": 999, "c": 3}, "ast": root}
    )
    assert evaluate_json_ast(req.ast, req.features) is False


def test_deep_or_chain_one_true() -> None:
    """OR over many false branches and one true branch."""
    children = [
        {"type": "condition", "op": "eq", "field": "n", "value": i} for i in range(12)
    ]
    children.append({"type": "condition", "op": "eq", "field": "n", "value": 42})
    raw = {"type": "or", "children": children}
    req = EvaluateAstRequest.model_validate({"features": {"n": 42}, "ast": raw})
    assert evaluate_json_ast(req.ast, req.features) is True


def test_deep_or_chain_all_false() -> None:
    raw = {
        "type": "or",
        "children": [
            {"type": "condition", "op": "eq", "field": "z", "value": 1},
            {"type": "condition", "op": "eq", "field": "z", "value": 2},
        ],
    }
    req = EvaluateAstRequest.model_validate({"features": {"z": 99}, "ast": raw})
    assert evaluate_json_ast(req.ast, req.features) is False


def test_mixed_and_over_or_precedence_via_tree_shape() -> None:
    """(amount >= 5000 AND is_vpn) OR (country == X AND is_bot) — tree encodes precedence."""
    tree = {
        "type": "or",
        "children": [
            {
                "type": "and",
                "children": [
                    {
                        "type": "condition",
                        "op": "gte",
                        "field": "amount",
                        "value": 5000,
                    },
                    {"type": "condition", "op": "is_true", "field": "is_vpn"},
                ],
            },
            {
                "type": "and",
                "children": [
                    {
                        "type": "condition",
                        "op": "eq",
                        "field": "country",
                        "value": "XX",
                    },
                    {"type": "condition", "op": "is_true", "field": "is_bot"},
                ],
            },
        ],
    }
    req = EvaluateAstRequest.model_validate(
        {
            "features": {
                "amount": 100,
                "is_vpn": False,
                "country": "XX",
                "is_bot": True,
            },
            "ast": tree,
        }
    )
    assert evaluate_json_ast(req.ast, req.features) is True


def test_pydantic_rejects_unknown_condition_op() -> None:
    bad = {"type": "condition", "op": "magic_op", "field": "x", "value": 1}
    with pytest.raises(ValidationError):
        EvaluateAstRequest.model_validate({"features": {}, "ast": bad})


def test_pydantic_rejects_unknown_node_type() -> None:
    bad = {
        "type": "xor",
        "children": [{"type": "condition", "op": "eq", "field": "x", "value": 1}],
    }
    with pytest.raises(ValidationError):
        EvaluateAstRequest.model_validate({"features": {}, "ast": bad})


def test_pydantic_rejects_extra_keys_on_condition() -> None:
    bad = {"type": "condition", "op": "eq", "field": "x", "value": 1, "hijack": True}
    with pytest.raises(ValidationError):
        EvaluateAstRequest.model_validate({"features": {}, "ast": bad})


def test_pydantic_rejects_empty_and_children() -> None:
    bad = {"type": "and", "children": []}
    with pytest.raises(ValidationError):
        EvaluateAstRequest.model_validate({"features": {}, "ast": bad})


def test_limits_reject_excessive_depth() -> None:
    raw = _nest_and_chain(MAX_AST_DEPTH + 1)
    with pytest.raises(ValidationError):
        EvaluateAstRequest.model_validate({"features": {"k": 1}, "ast": raw})


def test_limits_reject_excessive_node_count() -> None:
    raw = _binary_or_tree(8)
    parsed = TypeAdapter(JsonAstNode).validate_python(raw)
    assert ast_node_count(parsed) > MAX_AST_NODES
    with pytest.raises(ValidationError):
        EvaluateAstRequest.model_validate({"features": {"x": 1}, "ast": raw})


def test_rule_fail_closed_when_both_when_and_when_ast_present() -> None:
    """Ambiguous rule definitions must not match (fail closed)."""
    import decision_api.json_rules as jr

    jr._cached_packs = [
        {
            "version": 1,
            "_source_file": "amb.json",
            "rules": [
                {
                    "id": "ambiguous",
                    "when": [{"field": "amount", "op": "gte", "value": 1}],
                    "when_ast": {
                        "type": "condition",
                        "op": "eq",
                        "field": "amount",
                        "value": 9999,
                    },
                    "tags": ["t"],
                    "score_delta": 9,
                }
            ],
            "tag_rules": [],
        }
    ]
    hits, _, delta, _ = evaluate_json_rules({"amount": 10_000}, [])
    assert hits == [] and delta == 0.0


def test_rule_fail_closed_invalid_when_ast_skips_rule() -> None:
    import decision_api.json_rules as jr

    jr._cached_packs = [
        {
            "version": 1,
            "_source_file": "badast.json",
            "rules": [
                {
                    "id": "bad",
                    "when_ast": {
                        "type": "condition",
                        "op": "eq",
                        "field": "",
                        "value": 1,
                    },
                    "tags": ["t"],
                    "score_delta": 3,
                }
            ],
            "tag_rules": [],
        }
    ]
    hits, _, _, _ = evaluate_json_rules({"x": 1}, [])
    assert hits == []


def test_ast_condition_regex_empty_pattern_never_matches() -> None:
    raw = {"type": "condition", "op": "regex", "field": "email", "value": ""}
    req = EvaluateAstRequest.model_validate(
        {"features": {"email": "a@b.c"}, "ast": raw}
    )
    assert evaluate_json_ast(req.ast, req.features) is False


@pytest.mark.asyncio
async def test_http_evaluate_ast_success_and_validation_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from decision_api.main import app

    monkeypatch.setenv("API_KEYS", "kast")
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "false")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        ok = await client.post(
            "/v1/json-rules/evaluate-ast",
            headers={"x-api-key": "kast"},
            json={
                "features": {"amount": 7500},
                "ast": {
                    "type": "and",
                    "children": [
                        {
                            "type": "condition",
                            "op": "gte",
                            "field": "amount",
                            "value": 5000,
                        },
                        {
                            "type": "condition",
                            "op": "lt",
                            "field": "amount",
                            "value": 10_000,
                        },
                    ],
                },
            },
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["matched"] is True

        bad = await client.post(
            "/v1/json-rules/evaluate-ast",
            headers={"x-api-key": "kast"},
            json={"features": {}, "ast": {"type": "and", "children": []}},
        )
        assert bad.status_code == 422
