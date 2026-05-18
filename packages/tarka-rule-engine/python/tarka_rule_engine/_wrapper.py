"""Panic-safe :class:`RuleEngine` built on the PyO3 ``_native`` extension."""

from __future__ import annotations

import concurrent.futures
import logging
import os
from typing import Any, Final

from tarka_rule_engine._native import EvaluationContext
from tarka_rule_engine._native import RuleEngine as _RustRuleEngine

logger = logging.getLogger("tarka_rule_engine")

# Must match ``PANIC_TEST_VELOCITY_SENTINEL`` in ``src/lib.rs``.
PANIC_TEST_VELOCITY_SENTINEL: Final[int] = -911911

__all__ = ["EvaluationContext", "PANIC_TEST_VELOCITY_SENTINEL", "RuleEngine"]

_FFI_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=min(32, (os.cpu_count() or 4) * 4),
    thread_name_prefix="hetu_rust_ffi",
)


def _rust_ffi_timeout_sec() -> float | None:
    """
    Strict wall-clock ceiling for blocking PyO3 calls — Hetu stays coupled only within this budget.

    ``RULE_ENGINE_RUST_FFI_TIMEOUT_MS`` overrides :class:`~tarka_deploy_settings.DeploymentRuntimeSettings`.
    """
    raw = (os.environ.get("RULE_ENGINE_RUST_FFI_TIMEOUT_MS") or "").strip()
    if raw.isdigit():
        ms = int(raw)
        return None if ms <= 0 else ms / 1000.0
    try:
        from tarka_deploy_settings import DeploymentRuntimeSettings

        return DeploymentRuntimeSettings().rule_engine_rust_ffi_timeout_sec
    except Exception:
        pass
    profile = (os.environ.get("TARKA_DEPLOY_PROFILE") or "demo").strip().lower()
    ms = 150 if profile == "demo" else 50
    return ms / 1000.0


class RuleEngine:
    """Maps Rust panics (and other evaluation failures) to a fail-closed ``REVIEW`` decision."""

    __slots__ = ("_inner",)

    def __init__(self) -> None:
        self._inner = _RustRuleEngine()

    def evaluate(self, graph_score: float, velocity_1h: int) -> dict[str, Any]:
        timeout_sec = _rust_ffi_timeout_sec()

        def _invoke() -> dict[str, Any]:
            try:
                raw = self._inner.evaluate(graph_score, velocity_1h)
                out = dict(raw)
                out.setdefault("decision", "ALLOW")
                return out
            except TypeError:
                raise
            except GeneratorExit:
                raise
            except BaseException as exc:
                # PyO3 maps Rust panics to ``pyo3_runtime.PanicException``, a **BaseException** (not
                # ``Exception``), so a bare ``except Exception`` would not catch panics on Python 3.12+.
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                logger.critical(
                    "tarka_rule_engine_rust_evaluate_failure_fail_closed_review",
                    exc_info=True,
                    extra={"graph_score": graph_score, "velocity_1h": velocity_1h},
                )
                return {
                    "decision": "REVIEW",
                    "ok": False,
                    "graph_score": graph_score,
                    "velocity_1h": velocity_1h,
                    "error_class": type(exc).__name__,
                }

        if timeout_sec is None:
            return _invoke()
        fut = _FFI_EXECUTOR.submit(_invoke)
        try:
            return fut.result(timeout=timeout_sec)
        except concurrent.futures.TimeoutError:
            logger.warning(
                "tarka_rule_engine_rust_ffi_timeout fail_open velocity_1h=%s deadline_sec=%s",
                velocity_1h,
                timeout_sec,
            )
            return {
                "decision": "ALLOW",
                "ok": True,
                "graph_score": 0.0,
                "velocity_1h": velocity_1h,
                "ffi_timed_out": True,
            }
