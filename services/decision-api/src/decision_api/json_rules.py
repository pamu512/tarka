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

_MAX_FIELD_LEN = 128
_MAX_VALUE_LEN = 1024
_MAX_RULES_PER_PACK = 200
_MAX_CONDITIONS_PER_RULE = 20
_MAX_EVAL_TIME_MS = 50
_MAX_REGEX_PATTERN_LEN = 256

_cached_packs: list[dict[str, Any]] = []
_shadow_mode_packs: list[dict[str, Any]] = []


def load_rules() -> None:
    """Load all JSON rule packs from disk into memory. Call at startup."""
    global _cached_packs, _shadow_mode_packs
    path = Path(settings.rules_path)
    if not path.is_dir():
        _cached_packs = []
        _shadow_mode_packs = []
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
            # Treat user-provided regex as a restricted wildcard pattern to avoid regex injection.
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
    """
    Rollout gating: effective_at (scheduled start) and canary_percent (deterministic %).
    Simulation mode skips gating so offline runs see full rule effects.
    """
    if evaluation_mode == "simulation":
        return True, None

    # Champion–challenger (OSS #31): evaluate all packs that pass effective_at, ignoring canary_percent.
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


def _evaluate_pack(
    pack: dict[str, Any],
    features: dict[str, Any],
    redis_tags: list[str],
) -> tuple[list[str], list[str], float]:
    """Evaluate a single rule pack with safety limits."""
    hits: list[str] = []
    tags: list[str] = []
    delta = 0.0

    rules = pack.get("rules", [])
    if len(rules) > _MAX_RULES_PER_PACK:
        log.warning("Pack has %d rules, limiting to %d", len(rules), _MAX_RULES_PER_PACK)
        rules = rules[:_MAX_RULES_PER_PACK]

    t0 = time.monotonic()

    for rule in rules:
        elapsed_ms = (time.monotonic() - t0) * 1000
        if elapsed_ms > _MAX_EVAL_TIME_MS:
            log.warning("Rule evaluation timeout after %.1fms", elapsed_ms)
            break

        rid = rule.get("id", "unknown")
        when = rule.get("when", [])
        if not when or len(when) > _MAX_CONDITIONS_PER_RULE:
            continue
        if all(_match_condition(features, c) for c in when):
            hits.append(str(rid))
            tags.extend(str(t) for t in rule.get("tags", [])[:50])
            delta += float(rule.get("score_delta", 0))

    tag_rules = pack.get("tag_rules", [])
    for rule in tag_rules[:_MAX_RULES_PER_PACK]:
        elapsed_ms = (time.monotonic() - t0) * 1000
        if elapsed_ms > _MAX_EVAL_TIME_MS:
            break
        rid = rule.get("id", "")
        need = set(rule.get("any_tag", [])[:50])
        if need and need.intersection(set(redis_tags)):
            hits.append(str(rid))
            tags.extend(str(t) for t in rule.get("tags", [])[:50])
            delta += float(rule.get("score_delta", 0))

    return hits, tags, delta


def evaluate_json_rules(
    features: dict[str, Any],
    redis_tags: list[str],
    tenant_id: str | None = None,
    entity_id: str | None = None,
    *,
    evaluation_mode: str = "production",
    signal_tags: list[str] | None = None,
) -> tuple[list[str], list[str], float]:
    """Returns (rule_ids, tags_to_apply, score_delta).

    When *tenant_id* and *entity_id* are set, per-pack *canary_percent* and *effective_at* apply
    (unless *evaluation_mode* is ``simulation``).

    *signal_tags* are merged with *redis_tags* for ``tag_rules`` matching (ingress replay,
    geo mismatch, integrity supplements, etc.) without requiring those tags to be persisted in Redis.
    """
    tid = (tenant_id or "").strip() or "default"
    eid = (entity_id or "").strip() or "default"
    mode = evaluation_mode if evaluation_mode in ("production", "simulation", "challenger") else "production"

    merged_tags = list(redis_tags)
    if signal_tags:
        seen = set(merged_tags)
        for t in signal_tags:
            if t not in seen:
                seen.add(t)
                merged_tags.append(t)

    hits: list[str] = []
    tags: list[str] = []
    delta = 0.0
    for pack in _cached_packs:
        ok, _reason = _pack_should_apply(pack, tid, eid, evaluation_mode=mode)
        if not ok:
            continue
        pack_hits, pack_tags, pack_delta = _evaluate_pack(pack, features, merged_tags)
        hits.extend(pack_hits)
        tags.extend(pack_tags)
        delta += pack_delta
    return hits, tags, delta
