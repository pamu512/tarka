"""Tests for parallel Production/Candidate shadow orchestrator."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from decision_api.config import settings


@pytest.fixture
def candidate_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "decision_api.shadow_evaluator._candidate_packs",
        [{"version": 1, "rules": [], "_source_file": "candidate.json"}],
    )
    monkeypatch.setattr("decision_api.shadow_evaluator._candidate_enabled", True)


PROD_TUPLE = (
    ["p_hit"],
    ["p_tag"],
    5.0,
    ["prod.json"],
    {"engine": "rust"},
)


@pytest.mark.asyncio
async def test_parallel_returns_production_tuple(candidate_enabled: None) -> None:
    from decision_api import shadow_evaluator as se_mod
    from decision_api.shadow_evaluator import ShadowEvaluator

    cand_payload = {"candidate_decision": "review", "candidate_score": 55.0}

    async def mock_to_thread(fn: object, *args: object, **kwargs: object):
        if fn is se_mod._evaluate_json_rules_http_equivalent:
            return PROD_TUPLE
        if fn is se_mod._evaluate_candidate_sync:
            return cand_payload
        raise AssertionError(f"unexpected fn {fn}")

    req = MagicMock()
    req.app.state.clickhouse_client = None

    with patch.object(asyncio, "to_thread", mock_to_thread):
        out = await ShadowEvaluator(settings).evaluate_parallel(
            request=req,
            features={"k": 1},
            redis_tag_list=[],
            tenant_id="t1",
            entity_id="e1",
            signal_tags=[],
            trace_id="trace-1",
        )
    assert out == PROD_TUPLE


@pytest.mark.asyncio
async def test_production_http_exception_propagates(candidate_enabled: None) -> None:
    from decision_api import shadow_evaluator as se_mod
    from decision_api.shadow_evaluator import ShadowEvaluator

    exc = HTTPException(status_code=503, detail={"error": "rust_rule_engine_failed"})

    async def mock_to_thread(fn: object, *args: object, **kwargs: object):
        if fn is se_mod._evaluate_json_rules_http_equivalent:
            raise exc
        return {}

    req = MagicMock()
    req.app.state.clickhouse_client = None

    with patch.object(asyncio, "to_thread", mock_to_thread):
        with pytest.raises(HTTPException):
            await ShadowEvaluator(settings).evaluate_parallel(
                request=req,
                features={},
                redis_tag_list=[],
                tenant_id="t1",
                entity_id="e1",
                signal_tags=[],
                trace_id="trace-2",
            )


@pytest.mark.asyncio
async def test_wait_for_timeout_fallback_production_only(candidate_enabled: None) -> None:
    from decision_api import shadow_evaluator as se_mod
    from decision_api.shadow_evaluator import ShadowEvaluator

    async def immediate_timeout(_coro: object, timeout: float | None = None) -> None:
        raise asyncio.TimeoutError

    prod_calls = 0

    async def mock_to_thread(fn: object, *args: object, **kwargs: object):
        nonlocal prod_calls
        if fn is se_mod._evaluate_json_rules_http_equivalent:
            prod_calls += 1
            return PROD_TUPLE
        raise AssertionError("candidate eval should not run after outer timeout")

    req = MagicMock()
    req.app.state.clickhouse_client = None

    with (
        patch.object(asyncio, "wait_for", immediate_timeout),
        patch.object(asyncio, "to_thread", mock_to_thread),
    ):
        out = await ShadowEvaluator(settings).evaluate_parallel(
            request=req,
            features={},
            redis_tag_list=[],
            tenant_id="t1",
            entity_id="e1",
            signal_tags=[],
            trace_id="trace-3",
        )

    assert out == PROD_TUPLE
    assert prod_calls == 1
