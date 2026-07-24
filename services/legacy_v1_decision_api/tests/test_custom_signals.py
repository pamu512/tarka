"""Custom signal AST: Python resolver + merged features for rule evaluation."""

from __future__ import annotations

import logging
import time

import pytest
from pydantic import TypeAdapter, ValidationError

from decision_api.ast_evaluator import evaluate_json_ast
from decision_api.ast_models import EvaluateAstRequest, JsonAstNode
from decision_api.pack_evaluator import evaluate_packs_python
from tarka_core.engine_adapter import (
    SignalResolver,
    merge_features_with_resolved_from_ast,
    merge_features_with_resolved_from_packs,
    register_custom_signal,
    unregister_custom_signal,
)


def test_pydantic_accepts_custom_signal_in_tree() -> None:
    raw = {
        "type": "and",
        "children": [
            {
                "type": "custom_signal",
                "plugin_id": "demo_mul",
                "params": {"n": 4},
                "output_key": "score",
            },
            {"type": "condition", "op": "gte", "field": "score", "value": 7},
        ],
    }
    node = TypeAdapter(JsonAstNode).validate_python(raw)
    r = SignalResolver()

    def _demo_mul(params: dict, **_: object) -> int:
        return int(params.get("n", 0)) * 2

    r.register("demo_mul", _demo_mul)
    merged = merge_features_with_resolved_from_ast(
        {}, raw, tenant_id="t1", entity_id="e1", resolver=r
    )
    assert merged.get("score") == 8
    assert evaluate_json_ast(node, merged) is True


def test_unregistered_plugin_injects_null_and_condition_fails() -> None:
    raw = {
        "type": "and",
        "children": [
            {
                "type": "custom_signal",
                "plugin_id": "missing",
                "params": {},
                "output_key": "x",
            },
            {"type": "condition", "op": "gte", "field": "x", "value": 1},
        ],
    }
    node = TypeAdapter(JsonAstNode).validate_python(raw)
    r = SignalResolver()
    merged = merge_features_with_resolved_from_ast({"y": 1}, raw, resolver=r)
    assert merged.get("x") is None
    assert evaluate_json_ast(node, merged) is False


def test_timeout_logs_signal_resolution_failed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw = {
        "type": "custom_signal",
        "plugin_id": "slow",
        "params": {},
        "output_key": "z",
    }
    r = SignalResolver()

    def _slow(_p: dict, **_: object) -> str:
        time.sleep(0.2)
        return "done"

    r.register("slow", _slow)
    caplog.set_level(logging.WARNING)
    merged = merge_features_with_resolved_from_ast({}, raw, resolver=r, timeout_s=0.05)
    assert merged.get("z") is None
    assert any("SIGNAL_RESOLUTION_FAILED" in rec.message for rec in caplog.records)


def test_merge_from_packs_dedupes_same_plugin_call() -> None:
    packs = [
        {
            "version": 1,
            "_source_file": "p.json",
            "rules": [
                {
                    "id": "r1",
                    "when_ast": {
                        "type": "custom_signal",
                        "plugin_id": "const",
                        "params": {},
                        "output_key": "k",
                    },
                    "tags": [],
                    "score_delta": 1,
                },
                {
                    "id": "r2",
                    "when_ast": {
                        "type": "custom_signal",
                        "plugin_id": "const",
                        "params": {},
                        "output_key": "k",
                    },
                    "tags": [],
                    "score_delta": 1,
                },
            ],
            "tag_rules": [],
        }
    ]
    r = SignalResolver()
    calls: list[int] = []

    def _const(_p: dict, **_: object) -> int:
        calls.append(1)
        return 42

    r.register("const", _const)
    merged = merge_features_with_resolved_from_packs({}, packs, resolver=r)
    assert merged.get("k") == 42
    assert len(calls) == 1


def test_evaluate_ast_request_optional_tenant_entity() -> None:
    raw = {
        "type": "and",
        "children": [
            {
                "type": "custom_signal",
                "plugin_id": "tid_echo",
                "params": {},
                "output_key": "tenant",
            },
            {"type": "condition", "op": "eq", "field": "tenant", "value": "acme"},
        ],
    }
    r = SignalResolver()
    r.register(
        "tid_echo",
        lambda _p, *, tenant_id, **__: tenant_id,
    )
    req = EvaluateAstRequest.model_validate(
        {"features": {}, "ast": raw, "tenant_id": "acme", "entity_id": "u1"}
    )
    from tarka_core.engine_adapter import merge_features_with_resolved_from_ast

    merged = merge_features_with_resolved_from_ast(
        req.features,
        req.ast.model_dump(mode="json"),
        tenant_id=(req.tenant_id or "default"),
        entity_id=(req.entity_id or "default"),
        resolver=r,
    )
    assert evaluate_json_ast(req.ast, merged) is True


def test_pack_evaluator_hits_rule_with_custom_signal() -> None:
    register_custom_signal(
        "flag", lambda _p, features, **__: 1 if features.get("base") else 0
    )

    packs = [
        {
            "version": 1,
            "mode": "active",
            "_source_file": "sig.json",
            "rules": [
                {
                    "id": "hitme",
                    "when_ast": {
                        "type": "and",
                        "children": [
                            {
                                "type": "custom_signal",
                                "plugin_id": "flag",
                                "params": {},
                                "output_key": "derived",
                            },
                            {
                                "type": "condition",
                                "op": "eq",
                                "field": "derived",
                                "value": 1,
                            },
                        ],
                    },
                    "tags": ["t"],
                    "score_delta": 5.0,
                }
            ],
            "tag_rules": [],
        }
    ]
    try:
        out = evaluate_packs_python(
            packs,
            {"base": True},
            [],
            "tenant",
            "entity",
            "production",
            exclude_shadow=True,
        )
        assert "hitme" in out["rule_hits"]
        assert out["score_delta"] == 5.0
    finally:
        unregister_custom_signal("flag")


def test_params_too_large_rejected_by_pydantic() -> None:
    big = {"x": "y" * 9000}
    raw = {
        "type": "custom_signal",
        "plugin_id": "p",
        "params": big,
        "output_key": "k",
    }
    with pytest.raises(ValidationError):
        EvaluateAstRequest.model_validate({"features": {}, "ast": raw})
