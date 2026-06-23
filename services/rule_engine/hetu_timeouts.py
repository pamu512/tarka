"""Hetu (rule-engine): graph probe budgets and Rust FFI deadlines from validated deployment env."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def graph_context_fetch_timeout_sec() -> float | None:
    """
    Budget for Neo4j graph context probes — **decouples** rule evaluation from Cassandra/Janus tail latency.

    Explicit ``RULE_ENGINE_GRAPH_FETCH_TIMEOUT_MS`` wins over Pydantic-loaded ``.env`` so tests and
    shell overrides behave predictably.
    """
    raw = (os.environ.get("RULE_ENGINE_GRAPH_FETCH_TIMEOUT_MS") or "").strip()
    if raw.isdigit():
        ms = int(raw)
        return None if ms <= 0 else ms / 1000.0
    try:
        from tarka_deploy_settings import DeploymentRuntimeSettings

        return DeploymentRuntimeSettings().rule_engine_graph_fetch_timeout_sec
    except Exception:
        logger.debug("hetu_graph_timeout_fallback_profile", exc_info=True)
    profile = (os.environ.get("TARKA_DEPLOY_PROFILE") or "demo").strip().lower()
    ms = 50 if profile == "demo" else 100
    return ms / 1000.0


def rust_ffi_timeout_sec() -> float | None:
    """Strict wall-clock budget for Python→Rust Hetu FFI calls (see ``tarka_rule_engine._wrapper``)."""
    raw = (os.environ.get("RULE_ENGINE_RUST_FFI_TIMEOUT_MS") or "").strip()
    if raw.isdigit():
        ms = int(raw)
        return None if ms <= 0 else ms / 1000.0
    try:
        from tarka_deploy_settings import DeploymentRuntimeSettings

        return DeploymentRuntimeSettings().rule_engine_rust_ffi_timeout_sec
    except Exception:
        logger.debug("hetu_ffi_timeout_fallback_profile", exc_info=True)
    profile = (os.environ.get("TARKA_DEPLOY_PROFILE") or "demo").strip().lower()
    ms = 150 if profile == "demo" else 50
    return ms / 1000.0
