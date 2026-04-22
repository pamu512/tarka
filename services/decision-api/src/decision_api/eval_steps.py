from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal

import httpx

"""Bounded evaluation steps: timeout, bounded retries, onFailure (SKIP | REJECT) + metrics (#32)."""
log = logging.getLogger(__name__)

OnFailure = Literal["SKIP", "REJECT"]


def _metrics_inc(name: str) -> None:
    try:
        from observability import get_metrics

        get_metrics().inc(name)
    except Exception:
        pass


def _step_metric_suffix(step_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]+", "_", str(step_id).strip()).strip("_").lower()
    return safe or "unknown"


async def run_evaluation_step(
    step_id: str,
    factory: Callable[[], Awaitable[Any]],
    *,
    timeout_seconds: float,
    max_attempts: int = 1,
    on_failure: OnFailure = "SKIP",
    fallback: Any = None,
    retry_base_delay_seconds: float = 0.05,
) -> tuple[Any, dict[str, Any]]:
    """Run async *factory* with ``asyncio.wait_for`` and optional retries. Returns (value, trace_row)."""
    trace: dict[str, Any] = {"step": step_id, "attempts": 0, "status": "pending"}
    last_err: str | None = None
    attempts = max(1, min(int(max_attempts), 5))
    t0 = time.perf_counter()

    for attempt in range(attempts):
        trace["attempts"] = attempt + 1
        try:
            val = await asyncio.wait_for(factory(), timeout=timeout_seconds)
            trace["status"] = "ok"
            trace["duration_ms"] = round((time.perf_counter() - t0) * 1000, 2)
            _metrics_inc("tarka_eval_step_ok_total")
            _metrics_inc(f"tarka_eval_step_ok_total_step_{_step_metric_suffix(step_id)}")
            return val, trace
        except TimeoutError:
            last_err = "timeout"
            _metrics_inc("tarka_eval_step_timeout_total")
            _metrics_inc(f"tarka_eval_step_timeout_total_step_{_step_metric_suffix(step_id)}")
            log.warning("eval step %s timeout (attempt %s/%s)", step_id, attempt + 1, attempts)
        except httpx.HTTPError as e:
            last_err = f"http_error:{type(e).__name__}"
            _metrics_inc("tarka_eval_step_http_error_total")
            _metrics_inc(f"tarka_eval_step_http_error_total_step_{_step_metric_suffix(step_id)}")
            log.warning("eval step %s http error: %s", step_id, e)
        except Exception as e:
            last_err = f"error:{type(e).__name__}"
            _metrics_inc("tarka_eval_step_error_total")
            _metrics_inc(f"tarka_eval_step_error_total_step_{_step_metric_suffix(step_id)}")
            log.warning("eval step %s failed: %s", step_id, e)

        if attempt < attempts - 1:
            jitter = random.uniform(0, retry_base_delay_seconds)
            await asyncio.sleep(retry_base_delay_seconds + jitter)

    trace["status"] = "failed" if on_failure == "REJECT" else "skipped"
    trace["reason"] = last_err or "unknown"
    trace["duration_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    _metrics_inc("tarka_eval_step_skipped_total")
    _metrics_inc(f"tarka_eval_step_skipped_total_step_{_step_metric_suffix(step_id)}")
    if on_failure == "REJECT":
        raise RuntimeError(f"evaluation step {step_id} failed: {last_err}")
    return fallback, trace
