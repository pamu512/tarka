"""Evaluation step runner: timeout, retry, metrics hooks (#32)."""

import asyncio

import pytest
from decision_api.eval_steps import run_evaluation_step


@pytest.mark.asyncio
async def test_step_ok_first_try():
    async def ok():
        return "x"

    val, trace = await run_evaluation_step(
        "unit_ok",
        ok,
        timeout_seconds=1.0,
        max_attempts=1,
        fallback="bad",
    )
    assert val == "x"
    assert trace["status"] == "ok"


@pytest.mark.asyncio
async def test_step_timeout_then_fallback():
    async def slow():
        await asyncio.sleep(10)
        return "late"

    val, trace = await run_evaluation_step(
        "unit_slow",
        slow,
        timeout_seconds=0.05,
        max_attempts=1,
        on_failure="SKIP",
        fallback="fb",
    )
    assert val == "fb"
    assert trace["status"] == "skipped"
    assert trace.get("reason") == "timeout"


@pytest.mark.asyncio
async def test_step_retry_then_ok():
    n = {"c": 0}

    async def flaky():
        n["c"] += 1
        if n["c"] < 2:
            raise TimeoutError()
        return "ok"

    val, trace = await run_evaluation_step(
        "unit_retry",
        flaky,
        timeout_seconds=1.0,
        max_attempts=3,
        on_failure="SKIP",
        fallback=None,
    )
    assert val == "ok"
    assert trace["attempts"] == 2


@pytest.mark.asyncio
async def test_step_reject_raises():
    async def boom():
        raise RuntimeError("no")

    with pytest.raises(RuntimeError, match="evaluation step"):
        await run_evaluation_step(
            "unit_reject",
            boom,
            timeout_seconds=0.5,
            max_attempts=1,
            on_failure="REJECT",
            fallback=None,
        )
