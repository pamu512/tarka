"""
Shared shadow-rule evaluation and audit payloads (Prompts 189–191).

Active observation rules live in Redis ``shadow:rules:active``. Match evaluation supports
flat ``when`` arrays and optional Rust ``when_ast`` via ``tarka_rule_engine``.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

SHADOW_RULES_ACTIVE_KEY = "shadow:rules:active"
SHADOW_MATCH_STATS_PREFIX = "stats:shadow:"


def shadow_match_stats_key(rule_id: str) -> str:
    return f"{SHADOW_MATCH_STATS_PREFIX}{rule_id}:matches"


def build_shadow_matches_audit_records(
    matched_rule_ids: list[str],
    *,
    recorded_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Immutable audit JSON for ``audit_logs.shadow_matches`` (hypothesis rules that fired)."""
    ts = (recorded_at or datetime.now(UTC)).isoformat()
    return [{"rule_id": rid, "matched": True, "recorded_at": ts} for rid in matched_rule_ids]


def is_active_shadow_rule(rule: dict[str, Any]) -> bool:
    meta = rule.get("metadata")
    if not isinstance(meta, dict) or meta.get("is_shadow") is not True:
        return False
    status = str(rule.get("status") or "active").strip().lower()
    if status in ("disabled", "inactive", "paused"):
        return False
    return True


def iter_active_shadow_rules(blob: Any) -> list[dict[str, Any]]:
    if not isinstance(blob, list):
        return []
    out: list[dict[str, Any]] = []
    for item in blob:
        if not isinstance(item, dict):
            continue
        rules = item.get("rules")
        if isinstance(rules, list):
            mode = str(item.get("mode") or "active").strip().lower()
            if mode == "disabled":
                continue
            for rule in rules:
                if isinstance(rule, dict) and is_active_shadow_rule(rule):
                    out.append(rule)
        elif is_active_shadow_rule(item):
            out.append(item)
    return out


def _json_f64(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def match_flat_condition(features: dict[str, Any], cond: dict[str, Any]) -> bool:
    op = str(cond.get("op") or "eq")
    field = str(cond.get("field") or "")
    if not field:
        return False
    actual = features.get(field)
    expected = cond.get("value")
    if op == "eq":
        return actual == expected
    if op == "not_eq":
        return actual != expected
    if op == "gte":
        a, e = _json_f64(actual), _json_f64(expected)
        return a is not None and e is not None and a >= e
    if op == "gt":
        a, e = _json_f64(actual), _json_f64(expected)
        return a is not None and e is not None and a > e
    if op == "lte":
        a, e = _json_f64(actual), _json_f64(expected)
        return a is not None and e is not None and a <= e
    if op == "lt":
        a, e = _json_f64(actual), _json_f64(expected)
        return a is not None and e is not None and a < e
    if op == "in":
        arr = expected if isinstance(expected, list) else []
        return actual in arr
    if op == "not_in":
        arr = expected if isinstance(expected, list) else []
        return actual not in arr
    if op == "contains":
        if not isinstance(expected, str) or not expected:
            return False
        return expected in str(actual if actual is not None else "")
    if op == "starts_with":
        return isinstance(actual, str) and isinstance(expected, str) and actual.startswith(expected)
    if op == "ends_with":
        return isinstance(actual, str) and isinstance(expected, str) and actual.endswith(expected)
    if op == "is_true":
        return actual is True
    if op == "is_false":
        return actual is False
    if op == "exists":
        return field in features and features[field] is not None
    if op == "not_exists":
        return field not in features or features[field] is None
    return False


def rule_matches_flat(rule: dict[str, Any], features: dict[str, Any]) -> bool:
    when = rule.get("when")
    if not isinstance(when, list) or not when:
        return False
    return all(isinstance(c, dict) and match_flat_condition(features, c) for c in when)


def matched_shadow_rule_ids(rules: list[dict[str, Any]], features: dict[str, Any]) -> list[str]:
    if not rules:
        return []
    ast_rules = [r for r in rules if r.get("when_ast") is not None]
    flat_rules = [r for r in rules if r.get("when_ast") is None]
    matched: list[str] = []

    if ast_rules:
        try:
            from tarka_rule_engine import evaluate_observation_rules_json

            payload = json.loads(
                evaluate_observation_rules_json(
                    json.dumps(ast_rules, default=str),
                    json.dumps(features, default=str),
                ),
            )
            for rid, hit in (payload.get("shadow_results") or {}).items():
                if hit:
                    matched.append(str(rid))
        except ImportError:
            logger.debug(
                "shadow_hypothesis_rust_unavailable_skip_when_ast count=%d",
                len(ast_rules),
            )
        except Exception:
            logger.exception("shadow_hypothesis_rust_eval_failed")

    for rule in flat_rules:
        if rule_matches_flat(rule, features):
            rid = str(rule.get("id") or "").strip()
            if rid:
                matched.append(rid)

    seen: set[str] = set()
    unique: list[str] = []
    for rid in matched:
        if rid not in seen:
            seen.add(rid)
            unique.append(rid)
    return unique


def evaluate_shadow_matches_from_rules(
    rules: list[dict[str, Any]],
    features: dict[str, Any],
    *,
    recorded_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Evaluate rules and return audit rows for every hypothesis rule that fired."""
    matched = matched_shadow_rule_ids(rules, features)
    return build_shadow_matches_audit_records(matched, recorded_at=recorded_at)
