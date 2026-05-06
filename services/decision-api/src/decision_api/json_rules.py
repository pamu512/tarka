import hashlib
import json
import logging
import re
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from decision_api.config import settings
from tarka_core.internal_monitor import InternalMonitor

log = logging.getLogger(__name__)

# Last JSON rule engine metadata for audit/API (Rust vs Python, parity fallback flag).
_JSON_RULE_ENGINE_META: ContextVar[dict[str, Any]] = ContextVar(
    "json_rule_engine_metadata",
    default={"engine": "unknown", "fallback_active": False},
)


def get_json_rule_engine_metadata() -> dict[str, Any]:
    """Snapshot of engine used for the most recent evaluation in this async task."""
    return dict(_JSON_RULE_ENGINE_META.get())


def _set_json_rule_engine_metadata(meta: dict[str, Any]) -> None:
    _JSON_RULE_ENGINE_META.set(dict(meta))


def _configured_json_rules_engine_mode() -> str:
    v = (getattr(settings, "json_rules_engine", None) or "auto").strip().lower()
    if v in ("auto", "rust", "python"):
        return v
    return "auto"


# N3/N4: in-process rule hit counts since process start (reset on restart).
_rule_hit_counts: dict[str, int] = {}
_telemetry_started_at_unix: float = time.time()

_MAX_FIELD_LEN = 128
_MAX_VALUE_LEN = 1024
_MAX_RULES_PER_PACK = 200
_MAX_CONDITIONS_PER_RULE = 20
_MAX_REGEX_PATTERN_LEN = 256

_cached_packs: list[dict[str, Any]] = []
_shadow_mode_packs: list[dict[str, Any]] = []

# Optional PLG sandbox bundle (Postgres-backed); merged pack, not on disk.
SANDBOX_PLG_INDUSTRY_SOURCE_FILE = "sandbox_plg_industry_starter.json"
_plg_sandbox_runtime_pack: dict[str, Any] | None = None


def _attach_plg_sandbox_pack(active: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip any stale sandbox artifact from disk list, then append runtime PLG pack if configured."""
    filtered = [
        p for p in active if p.get("_source_file") != SANDBOX_PLG_INDUSTRY_SOURCE_FILE
    ]
    if _plg_sandbox_runtime_pack is None:
        return filtered
    merged = dict(_plg_sandbox_runtime_pack)
    merged.setdefault("_source_file", SANDBOX_PLG_INDUSTRY_SOURCE_FILE)
    return filtered + [merged]


def preload_plg_sandbox_runtime_pack(pack: dict[str, Any] | None) -> None:
    """Set the runtime PLG sandbox pack without reloading from disk (used before ``load_rules()``)."""
    global _plg_sandbox_runtime_pack
    _plg_sandbox_runtime_pack = None if pack is None else dict(pack)


def set_plg_sandbox_runtime_pack(pack: dict[str, Any] | None) -> None:
    """Replace (or clear) the in-memory PLG sandbox pack and reload disk rules."""
    preload_plg_sandbox_runtime_pack(pack)
    load_rules()


def _telemetry_key(pack_file: str, rule_id: str, kind: str) -> str:
    pf = (pack_file or "unknown")[:160]
    rid = (rule_id or "unknown")[:160]
    k = (kind or "rule")[:32]
    return f"{pf}|{rid}|{k}"


def record_rule_hit(pack_file: str, rule_id: str, kind: str = "rule") -> None:
    """Increment per-rule hit telemetry (N3) and optional Prometheus aggregate (N4)."""
    key = _telemetry_key(pack_file, rule_id, kind)
    _rule_hit_counts[key] = _rule_hit_counts.get(key, 0) + 1
    try:
        from observability import get_metrics

        get_metrics().inc("tarka_json_rule_hits_total")
    except Exception as exc:
        InternalMonitor.log_suppressed_error(
            exc, context="record_rule_hit_metrics", domain="observability"
        )


def get_rule_hit_telemetry() -> dict[str, Any]:
    """Snapshot of rule hit counts since boot for dashboards / Rules UI."""
    rows: list[dict[str, Any]] = []
    total = 0
    for key, n in sorted(_rule_hit_counts.items()):
        parts = key.split("|", 2)
        pack_file = parts[0] if len(parts) > 0 else "unknown"
        rule_id = parts[1] if len(parts) > 1 else "unknown"
        kind = parts[2] if len(parts) > 2 else "rule"
        total += n
        rows.append(
            {
                "pack_file": pack_file,
                "rule_id": rule_id,
                "kind": kind,
                "hits": n,
            }
        )
    return {
        "since_unix": _telemetry_started_at_unix,
        "total_hits": total,
        "unique_keys": len(rows),
        "rows": rows,
    }


def merge_redis_tags_with_signals(
    redis_tags: list[str], signal_tags: list[str] | None
) -> list[str]:
    """Append request-scoped signal tags to Redis-backed tags (deduplicated, order preserved)."""
    out = list(redis_tags)
    seen = set(out)
    for t in signal_tags or []:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _sync_rust_engine_packs() -> None:
    try:
        from decision_api.rust_rule_engine_ffi import sync_rust_packs_from_cache

        sync_rust_packs_from_cache()
    except Exception as e:
        log.warning(
            "rust_engine_pack_sync_failed",
            extra={
                "rust_ffi": True,
                "phase": "sync_after_load_rules",
                "exc_type": type(e).__name__,
                "exc_repr": repr(e),
            },
            exc_info=True,
        )


def build_emergency_static_rule_tuple() -> tuple[
    list[str], list[str], float, list[str]
]:
    """Fixed JSON-rule tuple when Rust FFI circuit is open and emergency policy is configured."""
    hits = json.loads(settings.rust_ffi_emergency_rule_hits_json or "[]")
    tags = json.loads(settings.rust_ffi_emergency_tags_json or "[]")
    contrib = json.loads(
        settings.rust_ffi_emergency_contributing_pack_files_json or "[]"
    )
    if not isinstance(hits, list):
        hits = ["rust_circuit_open"]
    if not isinstance(tags, list):
        tags = ["rust_ffi_circuit"]
    if not isinstance(contrib, list):
        contrib = ["emergency_static_policy"]
    hits_s = [str(x) for x in hits]
    tags_s = [str(x) for x in tags]
    contrib_s = [str(x) for x in contrib]
    delta = float(getattr(settings, "rust_ffi_emergency_score_delta", 80.0))
    return hits_s, tags_s, delta, contrib_s


def load_rules() -> None:
    """Load all JSON rule packs from disk into memory. Call at startup."""
    global _cached_packs, _shadow_mode_packs
    path = Path(settings.rules_path)
    if not path.is_dir():
        _cached_packs = _attach_plg_sandbox_pack([])
        _shadow_mode_packs = []
        _sync_rust_engine_packs()
        return
    active: list[dict[str, Any]] = []
    shadow: list[dict[str, Any]] = []
    for f in sorted(path.glob("*.json")):
        try:
            pack = json.loads(f.read_text(encoding="utf-8"))
            if pack.get("version", 1) != 1:
                continue
            pack["_source_file"] = f.name
            mode = pack.get("mode", "active")
            if mode == "disabled":
                continue
            elif mode == "shadow":
                shadow.append(pack)
            else:
                active.append(pack)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("skipping rule file %s: %s", f, e)
    _cached_packs = _attach_plg_sandbox_pack(active)
    _shadow_mode_packs = shadow
    log.info(
        "loaded %d disk-active + %d shadow rule packs from %s (runtime PLG sandbox=%s; engine_active=%d)",
        len(active),
        len(shadow),
        path,
        "yes" if _plg_sandbox_runtime_pack is not None else "no",
        len(_cached_packs),
    )
    _sync_rust_engine_packs()


def get_shadow_packs() -> list[dict[str, Any]]:
    """Return packs with mode == 'shadow'."""
    return list(_shadow_mode_packs)


def governance_summary() -> dict[str, Any]:
    """Operator view: active packs, rollout fields, shadow count (for Trust Center / ops)."""
    active_rows: list[dict[str, Any]] = []
    for pack in _cached_packs:
        active_rows.append(
            {
                "file": pack.get("_source_file"),
                "name": pack.get("name"),
                "mode": pack.get("mode", "active"),
                "canary_percent": pack.get("canary_percent"),
                "effective_at": pack.get("effective_at"),
                "approved_by": pack.get("approved_by"),
                "rule_count": len(pack.get("rules") or []),
            }
        )
    return {
        "active_pack_count": len(_cached_packs),
        "shadow_pack_count": len(_shadow_mode_packs),
        "packs": active_rows,
    }


def _json_f64_py(v: Any) -> float | None:
    """Parity with Rust ``json_f64`` (lib.rs): only JSON number scalars, not bool."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int) and not isinstance(v, bool):
        return float(v)
    if isinstance(v, float):
        return v
    return None


def _json_str_pythonish_actual(expected: Any, actual: Any) -> tuple[str, str]:
    """Parity with Rust ``json_str_pythonish`` + optional actual for ``contains``."""

    def _one(val: Any) -> str:
        if val is None:
            return "None"
        if isinstance(val, bool):
            return "true" if val else "false"
        if isinstance(val, int) and not isinstance(val, bool):
            return str(val)
        if isinstance(val, float):
            return str(val)
        if isinstance(val, str):
            return val
        try:
            return json.dumps(val, separators=(",", ":"), ensure_ascii=False)
        except (TypeError, ValueError):
            return str(val)

    return _one(expected), _one(actual)


def _json_value_display_for_regex(v: Any) -> str:
    """Subject string for ``regex`` op — serde_json ``Value`` ``Display`` / compact JSON."""
    try:
        return json.dumps(v, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        return str(v)


def _json_collection_equals(actual: Any, elem: Any) -> bool:
    """Approximate ``serde_json::Value`` equality for ``in`` / ``not_in`` list membership."""
    try:
        return json.dumps(
            actual, sort_keys=True, separators=(",", ":"), default=str
        ) == json.dumps(elem, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return actual == elem


def _match_condition(features: dict[str, Any], condition: dict[str, Any]) -> bool:
    """Flat ``when`` condition match — parity with Rust ``match_condition`` (lib.rs)."""
    op = condition.get("op", "eq")
    key = condition.get("field")
    if not key or len(str(key)) > _MAX_FIELD_LEN:
        return False
    actual = features.get(key)
    expected = condition.get("value")

    if expected is not None and len(str(expected)) > _MAX_VALUE_LEN:
        return False

    try:
        if op == "eq":
            return actual == expected
        if op == "not_eq":
            return actual != expected
        if op == "gte":
            av = _json_f64_py(actual)
            ev = _json_f64_py(expected)
            return av is not None and ev is not None and av >= ev
        if op == "gt":
            av = _json_f64_py(actual)
            ev = _json_f64_py(expected)
            return av is not None and ev is not None and av > ev
        if op == "lte":
            av = _json_f64_py(actual)
            ev = _json_f64_py(expected)
            return av is not None and ev is not None and av <= ev
        if op == "lt":
            av = _json_f64_py(actual)
            ev = _json_f64_py(expected)
            return av is not None and ev is not None and av < ev
        if op == "in":
            arr = expected if isinstance(expected, list) else None
            if arr is None:
                return False
            return any(_json_collection_equals(actual, x) for x in arr)
        if op == "not_in":
            arr = expected if isinstance(expected, list) else None
            if arr is None:
                return True
            return not any(_json_collection_equals(actual, x) for x in arr)
        if op == "contains":
            exp_s, act_s = _json_str_pythonish_actual(expected, actual)
            return bool(exp_s) and exp_s in act_s
        if op == "starts_with":
            suf = expected if isinstance(expected, str) else ""
            return isinstance(actual, str) and actual.startswith(suf)
        if op == "ends_with":
            suf = expected if isinstance(expected, str) else ""
            return isinstance(actual, str) and actual.endswith(suf)
        if op == "regex":
            if not expected:
                return False
            pattern = str(expected)
            if len(pattern) > _MAX_REGEX_PATTERN_LEN:
                return False
            escaped = re.escape(pattern)
            safe_re = "^" + escaped.replace(r"\*", ".*").replace(r"\?", ".") + "$"
            subj = _json_value_display_for_regex(actual if actual is not None else None)
            return bool(re.match(safe_re, subj, re.IGNORECASE))
        if op == "is_true":
            return actual is True
        if op == "is_false":
            return actual is False
        if op == "exists":
            return actual is not None
        if op == "not_exists":
            return actual is None
    except (TypeError, ValueError, OverflowError):
        return False
    return False


def _pack_experiment_bucket(tenant_id: str, entity_id: str, pack_key: str) -> int:
    """Deterministic 0..99 bucket for canary rollout (same entity always same bucket per pack)."""
    raw = f"{tenant_id}|{entity_id}|{pack_key}".encode("utf-8")
    h = hashlib.sha256(raw).hexdigest()
    return int(h[:8], 16) % 100


def _parse_effective_at(raw: Any) -> datetime | None:
    """RFC3339 / ISO-8601 parity with Rust ``parse_effective_at`` (lib.rs)."""
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError as exc:
        InternalMonitor.log_suppressed_error(
            exc,
            context="parse_effective_at_fromisoformat_fallback",
            domain="fraud_decisioning",
            level=logging.DEBUG,
        )
    try:
        dtnaive = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
        return dtnaive.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _pack_should_apply(
    pack: dict[str, Any],
    tenant_id: str,
    entity_id: str,
    *,
    evaluation_mode: str,
) -> tuple[bool, str | None]:
    if evaluation_mode == "simulation":
        return True, None

    if evaluation_mode == "challenger":
        eff = _parse_effective_at(pack.get("effective_at"))
        if eff is not None:
            now = datetime.now(timezone.utc)
            if now < eff:
                return False, "before_effective_at"
        return True, None

    eff = _parse_effective_at(pack.get("effective_at"))
    if eff is not None:
        now = datetime.now(timezone.utc)
        if now < eff:
            return False, "before_effective_at"

    cp = pack.get("canary_percent")
    if cp is None:
        return True, None
    try:
        pct = float(cp)
    except (TypeError, ValueError):
        return True, None
    if pct >= 100.0:
        return True, None
    if pct <= 0.0:
        return False, "canary_zero"

    key = str(pack.get("_source_file") or pack.get("name") or "pack")
    bucket = _pack_experiment_bucket(tenant_id, entity_id, key)
    if bucket >= pct:
        return False, "canary_excluded"
    return True, None


def _rust_eval_to_tuple(
    out: dict[str, Any],
) -> tuple[list[str], list[str], float, list[str]]:
    hits = [str(x) for x in (out.get("rule_hits") or [])]
    tags = [str(x) for x in (out.get("tags") or [])]
    delta = float(out.get("score_delta") or 0.0)
    contributing = [str(x) for x in (out.get("contributing_pack_files") or [])]
    return hits, tags, delta, contributing


def _apply_telemetry_from_rust(out: dict[str, Any]) -> None:
    for row in out.get("telemetry") or []:
        if not isinstance(row, dict):
            continue
        pf = str(row.get("pack_file") or "unknown")
        rid = str(row.get("rule_id") or "unknown")
        kind = str(row.get("kind") or "rule")
        record_rule_hit(pf, rid, kind)


def evaluate_json_rules(
    features: dict[str, Any],
    redis_tags: list[str],
    tenant_id: str | None = None,
    entity_id: str | None = None,
    *,
    evaluation_mode: str = "production",
    signal_tags: list[str] | None = None,
) -> tuple[list[str], list[str], float, list[str]]:
    """Evaluate active JSON rule packs (Rust engine when available, else Python).

    When ``TARKA_JSON_RULES_ENGINE`` selects Rust (``auto``/``rust`` with extension present),
    failures do **not** fall back to Python — see FFI circuit breaker in ``rust_rule_engine_ffi``.
    """
    from decision_api.rust_rule_engine_ffi import (
        evaluate_cached_packs_via_rust,
        should_use_rust_json_engine,
    )
    from decision_api.pack_evaluator import evaluate_packs_python

    cfg_mode = _configured_json_rules_engine_mode()
    tid = (tenant_id or "").strip() or "default"
    eid = (entity_id or "").strip() or "default"
    mode = (
        evaluation_mode
        if evaluation_mode in ("production", "simulation", "challenger")
        else "production"
    )
    merged = merge_redis_tags_with_signals(redis_tags, signal_tags)

    if should_use_rust_json_engine():
        out = evaluate_cached_packs_via_rust(
            features,
            redis_tags,
            tenant_id,
            entity_id,
            evaluation_mode=mode,
            signal_tags=signal_tags,
        )
        _apply_telemetry_from_rust(out)
        _set_json_rule_engine_metadata({"engine": "rust", "fallback_active": False})
        return _rust_eval_to_tuple(out)

    fallback_active = cfg_mode != "python"
    out = evaluate_packs_python(
        _cached_packs,
        features,
        merged,
        tid,
        eid,
        mode,
        exclude_shadow=True,
        fallback_active=fallback_active,
    )
    _apply_telemetry_from_rust(out)
    _set_json_rule_engine_metadata(
        {"engine": "python", "fallback_active": fallback_active}
    )
    return _rust_eval_to_tuple(out)


def evaluate_adhoc_packs_json(
    packs: list[dict[str, Any]],
    features: dict[str, Any],
    redis_tags: list[str],
    tenant_id: str | None = None,
    entity_id: str | None = None,
    *,
    evaluation_mode: str = "production",
    signal_tags: list[str] | None = None,
    record_telemetry: bool = False,
) -> tuple[list[str], list[str], float, list[str]]:
    """Evaluate arbitrary pack JSON (shadow packs, recommendation preview)."""
    from decision_api.rust_rule_engine_ffi import (
        evaluate_json_rules_via_rust,
        should_use_rust_json_engine,
    )
    from decision_api.pack_evaluator import evaluate_packs_python

    cfg_mode = _configured_json_rules_engine_mode()
    tid = (tenant_id or "").strip() or "default"
    eid = (entity_id or "").strip() or "default"
    mode = (
        evaluation_mode
        if evaluation_mode in ("production", "simulation", "challenger")
        else "production"
    )
    merged = merge_redis_tags_with_signals(redis_tags, signal_tags)

    if should_use_rust_json_engine():
        out = evaluate_json_rules_via_rust(
            packs,
            features,
            redis_tags,
            tenant_id,
            entity_id,
            evaluation_mode=mode,
            signal_tags=signal_tags,
        )
        if record_telemetry:
            _apply_telemetry_from_rust(out)
        _set_json_rule_engine_metadata({"engine": "rust", "fallback_active": False})
        return _rust_eval_to_tuple(out)

    fallback_active = cfg_mode != "python"
    out = evaluate_packs_python(
        packs,
        features,
        merged,
        tid,
        eid,
        mode,
        exclude_shadow=False,
        fallback_active=fallback_active,
    )
    if record_telemetry:
        _apply_telemetry_from_rust(out)
    _set_json_rule_engine_metadata(
        {"engine": "python", "fallback_active": fallback_active}
    )
    return _rust_eval_to_tuple(out)


def search_omni_rules(query: str, limit: int = 24) -> list[dict[str, Any]]:
    """Substring match over active pack metadata + rule ids/descriptions (command palette)."""
    qn = (query or "").strip().lower()
    if not qn or limit <= 0:
        return []
    out: list[dict[str, Any]] = []
    for pack in _cached_packs:
        src = str(pack.get("_source_file") or "unknown.json")
        pname = str(pack.get("name") or "").strip() or (
            src.removesuffix(".json") if src.lower().endswith(".json") else src
        )
        for rule in pack.get("rules") or []:
            if not isinstance(rule, dict):
                continue
            rid = str(rule.get("id") or "")
            desc = str(rule.get("description") or "")
            blob = f"{rid} {desc} {pname} {src}".lower()
            if qn not in blob:
                continue
            sub = desc if len(desc) <= 160 else f"{desc[:159]}…"
            out.append(
                {
                    "rule_id": rid,
                    "pack_file": src,
                    "pack_name": pname,
                    "label": rid or "(unnamed rule)",
                    "subtitle": sub or None,
                }
            )
            if len(out) >= limit:
                return out
        for rule in pack.get("tag_rules") or []:
            if not isinstance(rule, dict):
                continue
            rid = str(rule.get("id") or "")
            desc = str(rule.get("description") or "")
            blob = f"{rid} {desc} {pname} {src} tag".lower()
            if qn not in blob:
                continue
            sub = desc if len(desc) <= 160 else f"{desc[:159]}…"
            out.append(
                {
                    "rule_id": rid,
                    "pack_file": src,
                    "pack_name": pname,
                    "label": rid or "(tag rule)",
                    "subtitle": (sub or "tag rule") + " · tag_rules",
                }
            )
            if len(out) >= limit:
                return out
    return out
