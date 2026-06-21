"""Rust ``tarka_rule_engine`` (PyO3) FFI, sliding-window circuit breaker, and structured failure logs.

Kept separate from :mod:`decision_api.decision_engine` so callers (e.g. ``json_rules``) do not
import SQLAlchemy / DB layers.
"""

from __future__ import annotations

import json
import logging
import traceback
from typing import Any

from tarka_core.engine_adapter import merge_features_with_resolved_from_packs

from decision_api.config import settings

log = logging.getLogger(__name__)

_rust_mod: Any | bool | None = None


def _rust() -> Any | None:
    global _rust_mod
    if _rust_mod is None:
        try:
            import tarka_rule_engine as tre  # type: ignore[import-not-found]

            _rust_mod = tre
        except ImportError:
            _rust_mod = False
    return _rust_mod if _rust_mod is not False else None


def rust_json_rules_engine_available() -> bool:
    return _rust() is not None


def parse_ast_malformed_detail(exc: BaseException) -> dict[str, Any] | None:
    """Return decoded JSON from ``JsonAstMalformedError.args[0]``, if present."""
    tre = _rust()
    if tre is None:
        return None
    if not isinstance(exc, tre.JsonAstMalformedError):
        return None
    if not exc.args:
        return None
    raw = exc.args[0]
    if not isinstance(raw, str):
        return None
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        return {"message": raw}


def sync_rust_packs_from_cache() -> bool:
    """Mirror in-memory ``_cached_packs`` into the Rust extension (call after ``load_rules``)."""
    tre = _rust()
    if tre is None:
        return False
    try:
        from decision_api.json_rules import _cached_packs

        tre.sync_packs_json(json.dumps(_cached_packs))
        return True
    except Exception as e:
        log.error(
            "rust_ffi_sync_packs_failed",
            extra={
                "rust_ffi": True,
                "phase": "sync_packs_json",
                "exc_type": type(e).__name__,
                "exc_repr": repr(e),
                "traceback": traceback.format_exc(),
            },
        )
        return False


def _json_rules_engine_mode() -> str:
    v = (getattr(settings, "json_rules_engine", None) or "auto").strip().lower()
    if v in ("auto", "rust", "python"):
        return v
    return "auto"


def _summarize_rust_eval_inputs(
    merged_features: dict[str, Any],
    *,
    redis_tags: list[str],
    tenant_id: str,
    entity_id: str,
    evaluation_mode: str,
    signal_tags: list[str] | None,
    adhoc_pack_files: list[str] | None = None,
) -> dict[str, Any]:
    max_chars = int(getattr(settings, "rust_ffi_log_payload_max_chars", 8192))
    raw = json.dumps(merged_features, default=str, sort_keys=True)
    ctx: dict[str, Any] = {
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "evaluation_mode": evaluation_mode,
        "feature_key_count": len(merged_features),
        "feature_keys_sample": sorted(merged_features.keys())[:200],
        "redis_tag_count": len(redis_tags),
        "redis_tags_sample": redis_tags[:48],
        "signal_tags_sample": list(signal_tags or [])[:48],
        "merged_features_json_truncated": raw[:max_chars],
        "merged_features_was_truncated": len(raw) > max_chars,
    }
    if adhoc_pack_files is not None:
        ctx["adhoc_pack_files_sample"] = adhoc_pack_files[:100]
    return ctx


def _log_rust_ffi_failure(
    exc: BaseException,
    *,
    phase: str,
    traceback_text: str,
    context: dict[str, Any],
) -> None:
    from decision_api.rust_ffi_circuit import circuit_is_open, failures_in_window

    n = failures_in_window()
    log.error(
        "rust_ffi_evaluation_failed phase=%s exc_type=%s circuit_open=%s failures_in_window=%s",
        phase,
        type(exc).__name__,
        circuit_is_open(),
        n,
        extra={
            "rust_ffi": True,
            "phase": phase,
            "exc_type": type(exc).__name__,
            "exc_repr": repr(exc),
            "exc_args": exc.args,
            "traceback": traceback_text,
            "payload_context": context,
            "failures_in_window": n,
            "circuit_open": circuit_is_open(),
        },
    )


def evaluate_json_rules_via_rust(
    packs: list[dict[str, Any]],
    features: dict[str, Any],
    redis_tags: list[str],
    tenant_id: str | None,
    entity_id: str | None,
    *,
    evaluation_mode: str = "production",
    signal_tags: list[str] | None = None,
) -> dict[str, Any]:
    """Evaluate packs via PyO3 (adhoc path). See package docstring in former ``decision_engine``."""
    from decision_api.rust_ffi_circuit import (
        circuit_is_open,
        failures_in_window,
        record_rust_ffi_failure,
        record_rust_ffi_success,
    )
    from decision_api.rust_rule_engine_exceptions import (
        RustRuleEngineCircuitOpenError,
        RustRuleEngineInvocationFailed,
    )

    if circuit_is_open():
        n = failures_in_window()
        raise RustRuleEngineCircuitOpenError(
            "Rust JSON rule engine circuit is open (recent FFI failure burst)",
            failures_in_window=n,
        )

    tre = _rust()
    if tre is None:
        raise RuntimeError("tarka_rule_engine is not installed")

    tid = (tenant_id or "").strip() or "default"
    eid = (entity_id or "").strip() or "default"
    mode = (
        evaluation_mode
        if evaluation_mode in ("production", "simulation", "challenger")
        else "production"
    )
    st_opt = json.dumps(list(signal_tags)) if signal_tags else None
    merged_features = merge_features_with_resolved_from_packs(
        features if isinstance(features, dict) else {},
        packs,
        tenant_id=tid,
        entity_id=eid,
    )
    pack_files = [
        str(p.get("_source_file") or "") for p in packs if isinstance(p, dict)
    ][:120]
    ctx = _summarize_rust_eval_inputs(
        merged_features,
        redis_tags=redis_tags,
        tenant_id=tid,
        entity_id=eid,
        evaluation_mode=mode,
        signal_tags=signal_tags,
        adhoc_pack_files=pack_files,
    )
    try:
        out_json = tre.evaluate_adhoc_packs_rust(
            json.dumps(packs),
            json.dumps(merged_features),
            json.dumps(redis_tags),
            tid,
            eid,
            mode,
            st_opt,
        )
        out = json.loads(out_json)
    except Exception as exc:
        fw = record_rust_ffi_failure()
        tb = traceback.format_exc()
        ctx_fail = {
            **ctx,
            "failures_in_window_after": fw,
            "adhoc_pack_json_head": json.dumps(packs, default=str)[:4096],
        }
        _log_rust_ffi_failure(
            exc, phase="evaluate_adhoc_packs_rust", traceback_text=tb, context=ctx_fail
        )
        raise RustRuleEngineInvocationFailed(
            f"Rust evaluate_adhoc_packs_rust failed: {exc}",
            cause=exc,
            context=ctx_fail,
        ) from exc

    record_rust_ffi_success()
    return out


def evaluate_cached_packs_via_rust(
    features: dict[str, Any],
    redis_tags: list[str],
    tenant_id: str | None,
    entity_id: str | None,
    *,
    evaluation_mode: str = "production",
    signal_tags: list[str] | None = None,
) -> dict[str, Any]:
    """Evaluate globally synced packs (production path)."""
    from decision_api.rust_ffi_circuit import (
        circuit_is_open,
        failures_in_window,
        record_rust_ffi_failure,
        record_rust_ffi_success,
    )
    from decision_api.rust_rule_engine_exceptions import (
        RustRuleEngineCircuitOpenError,
        RustRuleEngineInvocationFailed,
    )

    if circuit_is_open():
        n = failures_in_window()
        raise RustRuleEngineCircuitOpenError(
            "Rust JSON rule engine circuit is open (recent FFI failure burst)",
            failures_in_window=n,
        )

    tre = _rust()
    if tre is None:
        raise RuntimeError("tarka_rule_engine is not installed")

    tid = (tenant_id or "").strip() or "default"
    eid = (entity_id or "").strip() or "default"
    mode = (
        evaluation_mode
        if evaluation_mode in ("production", "simulation", "challenger")
        else "production"
    )
    st_opt = json.dumps(list(signal_tags)) if signal_tags else None
    from decision_api import json_rules as jr

    merged_features = merge_features_with_resolved_from_packs(
        features if isinstance(features, dict) else {},
        jr._cached_packs,
        tenant_id=tid,
        entity_id=eid,
    )
    ctx = _summarize_rust_eval_inputs(
        merged_features,
        redis_tags=redis_tags,
        tenant_id=tid,
        entity_id=eid,
        evaluation_mode=mode,
        signal_tags=signal_tags,
        adhoc_pack_files=[
            str(p.get("_source_file") or "")
            for p in jr._cached_packs
            if isinstance(p, dict)
        ][:120],
    )
    try:
        out_json = tre.evaluate_json_rules_rust(
            json.dumps(merged_features),
            json.dumps(redis_tags),
            tid,
            eid,
            mode,
            st_opt,
        )
        out = json.loads(out_json)
    except Exception as exc:
        fw = record_rust_ffi_failure()
        tb = traceback.format_exc()
        ctx_fail = {**ctx, "failures_in_window_after": fw}
        _log_rust_ffi_failure(
            exc, phase="evaluate_json_rules_rust", traceback_text=tb, context=ctx_fail
        )
        raise RustRuleEngineInvocationFailed(
            f"Rust evaluate_json_rules_rust failed: {exc}",
            cause=exc,
            context=ctx_fail,
        ) from exc

    record_rust_ffi_success()
    return out


def should_use_rust_json_engine() -> bool:
    mode = _json_rules_engine_mode()
    if mode == "python":
        return False
    if mode == "rust":
        return rust_json_rules_engine_available()
    return rust_json_rules_engine_available()
