import json
import logging
import re
import time
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
) -> tuple[list[str], list[str], float]:
    """Returns (rule_ids, tags_to_apply, score_delta)."""
    hits: list[str] = []
    tags: list[str] = []
    delta = 0.0
    for pack in _cached_packs:
        pack_hits, pack_tags, pack_delta = _evaluate_pack(pack, features, redis_tags)
        hits.extend(pack_hits)
        tags.extend(pack_tags)
        delta += pack_delta
    return hits, tags, delta
