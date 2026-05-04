import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from decision_api.config import settings

log = logging.getLogger(__name__)

try:
    import tarka_rule_engine as _tarka_rule_engine
except ImportError:  # pragma: no cover — CI builds the extension explicitly
    _tarka_rule_engine = None  # type: ignore[assignment]


def _require_rust_engine() -> Any:
    if _tarka_rule_engine is None:
        msg = (
            "tarka_rule_engine (Rust/PyO3) is required for rule evaluation. "
            "Build and install from services/rule-engine: pip install maturin && maturin develop --release"
        )
        raise RuntimeError(msg)
    return _tarka_rule_engine


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
_last_rust_sync_fingerprint: str | None = None


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
    except Exception:
        pass


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


def _sync_rust_active_packs() -> None:
    global _last_rust_sync_fingerprint
    tre = _require_rust_engine()
    payload = json.dumps(_cached_packs, default=str)
    tre.sync_packs_json(payload)
    _last_rust_sync_fingerprint = hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _ensure_rust_engine_has_current_packs() -> None:
    """Sync active packs into the Rust engine when the in-memory list changed (including tests)."""
    global _last_rust_sync_fingerprint
    tre = _require_rust_engine()
    payload = json.dumps(_cached_packs, default=str)
    fp = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    if fp == _last_rust_sync_fingerprint:
        return
    tre.sync_packs_json(payload)
    _last_rust_sync_fingerprint = fp


def load_rules() -> None:
    """Load all JSON rule packs from disk into memory. Call at startup."""
    global _cached_packs, _shadow_mode_packs
    path = Path(settings.rules_path)
    if not path.is_dir():
        global _last_rust_sync_fingerprint
        _cached_packs = []
        _shadow_mode_packs = []
        _last_rust_sync_fingerprint = None
        if _tarka_rule_engine is not None:
            _tarka_rule_engine.sync_packs_json("[]")
            _last_rust_sync_fingerprint = hashlib.sha256(b"[]").hexdigest()
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
    _cached_packs = active
    _shadow_mode_packs = shadow
    log.info("loaded %d active + %d shadow rule packs from %s", len(active), len(shadow), path)
    if _tarka_rule_engine is not None:
        _sync_rust_active_packs()


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


def _match_condition(features: dict[str, Any], condition: dict[str, Any]) -> bool:
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
            return actual is not None and float(actual) >= float(expected)
        if op == "gt":
            return actual is not None and float(actual) > float(expected)
        if op == "lte":
            return actual is not None and float(actual) <= float(expected)
        if op == "lt":
            return actual is not None and float(actual) < float(expected)
        if op == "in":
            return actual in (expected or [])
        if op == "not_in":
            return actual not in (expected or [])
        if op == "contains":
            return str(expected) in str(actual or "")
        if op == "starts_with":
            return str(actual or "").startswith(str(expected))
        if op == "ends_with":
            return str(actual or "").endswith(str(expected))
        if op == "regex":
            if not expected:
                return False
            pattern = str(expected)
            if len(pattern) > _MAX_REGEX_PATTERN_LEN:
                return False
            escaped = re.escape(pattern)
            safe_re = "^" + escaped.replace(r"\*", ".*").replace(r"\?", ".") + "$"
            return bool(re.match(safe_re, str(actual or ""), re.IGNORECASE))
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
        return dt
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


def _rust_eval_to_tuple(out: dict[str, Any]) -> tuple[list[str], list[str], float, list[str]]:
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
    """Evaluate active JSON rule packs via the Rust engine (PyO3)."""
    _ensure_rust_engine_has_current_packs()
    tre = _require_rust_engine()
    tid = (tenant_id or "").strip() or "default"
    eid = (entity_id or "").strip() or "default"
    mode = evaluation_mode if evaluation_mode in ("production", "simulation", "challenger") else "production"
    st_json = json.dumps(list(signal_tags)) if signal_tags else None
    raw = tre.evaluate_json_rules_rust(
        json.dumps(features, default=str),
        json.dumps(redis_tags),
        tid,
        eid,
        mode,
        st_json,
    )
    out = json.loads(raw)
    _apply_telemetry_from_rust(out)
    h, t, d, c = _rust_eval_to_tuple(out)
    return h, t, d, c


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
    """Evaluate arbitrary pack JSON (shadow packs, recommendation preview) via Rust."""
    tre = _require_rust_engine()
    tid = (tenant_id or "").strip() or "default"
    eid = (entity_id or "").strip() or "default"
    mode = evaluation_mode if evaluation_mode in ("production", "simulation", "challenger") else "production"
    st_json = json.dumps(list(signal_tags)) if signal_tags else None
    raw = tre.evaluate_adhoc_packs_rust(
        json.dumps(packs, default=str),
        json.dumps(features, default=str),
        json.dumps(redis_tags),
        tid,
        eid,
        mode,
        st_json,
    )
    out = json.loads(raw)
    if record_telemetry:
        _apply_telemetry_from_rust(out)
    h, t, d, c = _rust_eval_to_tuple(out)
    return h, t, d, c
