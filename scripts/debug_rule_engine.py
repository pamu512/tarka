#!/usr/bin/env python3
"""Debug a single JSON rule pack against mock features / signal tags.

Uses the same evaluation path as production ``evaluate_json_rules`` by injecting
an ad-hoc pack into the in-process cache (``_cached_packs``).

Usage (from repo root):

    TARKA_JSON_RULES_ENGINE=python python scripts/debug_rule_engine.py

    python scripts/debug_rule_engine.py --rule-file path/to/rule.json
    python scripts/debug_rule_engine.py --features '{"amount": 6000, "event_type": "payment"}'

Exit code 0 when at least one rule fires; 1 when none fire; 2 on config errors.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DECISION_SRC = _REPO_ROOT / "services" / "decision-api" / "src"
_SHARED = _REPO_ROOT / "services" / "shared"
for _p in (_DECISION_SRC, _SHARED):
    _token = str(_p)
    if _token not in sys.path:
        sys.path.insert(0, _token)

# Deterministic Python evaluator (no Rust wheel required for local debug).
os.environ.setdefault("TARKA_JSON_RULES_ENGINE", "python")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from decision_api import json_rules  # noqa: E402
from decision_api.json_rules import (  # noqa: E402
    _match_condition,
    evaluate_json_rules,
    get_json_rule_engine_metadata,
    merge_redis_tags_with_signals,
)

# Avoid observability init when running outside FastAPI.
json_rules.record_rule_hit = lambda *args, **kwargs: None  # type: ignore[method-assign]


# --- Edit these defaults to match the rule you are debugging -----------------

MOCK_FEATURES: dict[str, Any] = {
    "amount": 6000.0,
    "event_type": "payment",
    "event_count_1h": 12,
    "is_vpn": False,
}

MOCK_REDIS_TAGS: list[str] = []

MOCK_SIGNAL_TAGS: list[str] = [
    "graph:neighbor_device_count_high",
    "sdk:vpn",
]

MOCK_RULE_PACK: dict[str, Any] = {
    "version": 1,
    "mode": "active",
    "name": "debug_rule_pack",
    "_source_file": "debug_rule_pack.json",
    "rules": [
        {
            "id": "high_payment_amount",
            "when": [
                {"op": "gte", "field": "amount", "value": 5000},
                {"op": "eq", "field": "event_type", "value": "payment"},
            ],
            "tags": ["amount:high"],
            "score_delta": 25.0,
        },
        {
            "id": "velocity_spike_1h",
            "when": [{"op": "gte", "field": "event_count_1h", "value": 10}],
            "tags": ["velocity:high_1h"],
            "score_delta": 10.0,
        },
    ],
    "tag_rules": [
        {
            "id": "graph_neighbor_device_ring",
            "any_tag": ["graph:neighbor_device_count_high"],
            "tags": ["graph:device_ring_suspect"],
            "score_delta": 15.0,
        },
    ],
}


def _fmt(value: Any) -> str:
    try:
        return json.dumps(value, default=str)
    except TypeError:
        return repr(value)


def debug_flat_when(
    rule_id: str,
    when: list[dict[str, Any]],
    features: dict[str, Any],
) -> bool:
    """Print per-condition results for flat ``when`` arrays; return overall match."""
    print(f"\n  rule {rule_id!r} — flat when ({len(when)} condition(s))")
    if not when:
        print("    MISS: empty when")
        return False

    all_ok = True
    for idx, cond in enumerate(when, start=1):
        if not isinstance(cond, dict):
            print(f"    [{idx}] MISS: condition is not an object: {cond!r}")
            all_ok = False
            continue
        op = cond.get("op", "eq")
        field = cond.get("field")
        expected = cond.get("value")
        actual = features.get(field) if field else None
        ok = _match_condition(features, cond)
        status = "MET" if ok else "MISS"
        print(
            f"    [{idx}] {status}: field={field!r} op={op!r} "
            f"expected={_fmt(expected)} actual={_fmt(actual)}"
        )
        if not ok:
            all_ok = False
    verdict = "FIRES" if all_ok else "skipped"
    print(f"    => {verdict}")
    return all_ok


def debug_tag_rule(
    rule_id: str,
    any_tag: list[str],
    merged_tags: set[str],
) -> bool:
    """Print tag_rule ``any_tag`` matching against merged redis + signal tags."""
    print(f"\n  tag_rule {rule_id!r} — any_tag ({len(any_tag)} required tag(s))")
    if not any_tag:
        print("    MISS: any_tag is empty")
        return False
    need = {str(t) for t in any_tag if isinstance(t, str)}
    for tag in sorted(need):
        present = tag in merged_tags
        status = "MET" if present else "MISS"
        print(f"    {status}: {tag!r} in merged_tags={present}")
    matched = bool(need & merged_tags)
    print(f"    => {'FIRES' if matched else 'skipped'}")
    return matched


def debug_pack(
    pack: dict[str, Any],
    features: dict[str, Any],
    redis_tags: list[str],
    signal_tags: list[str],
) -> None:
    """Walk rules in a pack and print condition-level debug before engine eval."""
    merged_tag_list = merge_redis_tags_with_signals(redis_tags, signal_tags)
    merged_tags = set(merged_tag_list)

    print("=" * 72)
    print(f"Pack: {pack.get('name') or pack.get('_source_file') or 'unknown'}")
    print(f"Features: {_fmt(features)}")
    print(f"redis_tags: {_fmt(redis_tags)}")
    print(f"signal_tags: {_fmt(signal_tags)}")
    print(f"merged_tags (for tag_rules): {_fmt(sorted(merged_tags))}")

    for rule in pack.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        rid = str(rule.get("id") or "unknown")
        when = rule.get("when")
        if isinstance(when, list):
            debug_flat_when(rid, when, features)
        elif rule.get("when_ast") is not None:
            print(
                f"\n  rule {rid!r} — when_ast present (use rule compiler dry-run for AST trace)"
            )
        else:
            print(f"\n  rule {rid!r} — no when / when_ast")

    for tr in pack.get("tag_rules") or []:
        if not isinstance(tr, dict):
            continue
        rid = str(tr.get("id") or "tagrule")
        any_tag = tr.get("any_tag") or []
        if isinstance(any_tag, list):
            debug_tag_rule(rid, any_tag, merged_tags)


def decision_from_score_delta(base: float, score_delta: float) -> str:
    """Rough decision band using default decision-api thresholds (10 + delta baseline)."""
    final = base + score_delta
    if final >= 80:
        return "deny"
    if final >= 50:
        return "review"
    return "allow"


def run_evaluation(
    pack: dict[str, Any],
    features: dict[str, Any],
    redis_tags: list[str],
    signal_tags: list[str],
    *,
    tenant_id: str,
    entity_id: str,
) -> tuple[list[str], list[str], float, list[str]]:
    json_rules._cached_packs = [pack]
    return evaluate_json_rules(
        features,
        redis_tags,
        tenant_id,
        entity_id,
        evaluation_mode="simulation",
        signal_tags=signal_tags,
    )


def _load_pack(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected JSON object at root")
    if "rules" not in raw and "tag_rules" not in raw:
        # Single rule object → wrap as pack
        raw = {
            "version": 1,
            "mode": "active",
            "name": path.stem,
            "_source_file": path.name,
            "rules": [raw],
            "tag_rules": [],
        }
    raw.setdefault("version", 1)
    raw.setdefault("mode", "active")
    raw.setdefault("_source_file", path.name)
    raw.setdefault("rules", [])
    raw.setdefault("tag_rules", [])
    return raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rule-file",
        type=Path,
        help="JSON rule pack or single rule object to evaluate",
    )
    parser.add_argument(
        "--features",
        type=str,
        help="JSON object overriding mock features",
    )
    parser.add_argument(
        "--redis-tags",
        type=str,
        help="JSON array of redis-backed tags",
    )
    parser.add_argument(
        "--signal-tags",
        type=str,
        help="JSON array of request-scoped signal tags",
    )
    parser.add_argument("--tenant-id", default="debug-tenant")
    parser.add_argument("--entity-id", default="debug-entity")
    parser.add_argument(
        "--base-score",
        type=float,
        default=10.0,
        help="Baseline score before rule delta (evaluate uses 10 + deltas)",
    )
    args = parser.parse_args()

    pack = MOCK_RULE_PACK
    if args.rule_file is not None:
        if not args.rule_file.is_file():
            print(f"error: rule file not found: {args.rule_file}", file=sys.stderr)
            return 2
        try:
            pack = _load_pack(args.rule_file)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"error: failed to load rule file: {exc}", file=sys.stderr)
            return 2

    features = dict(MOCK_FEATURES)
    if args.features:
        try:
            parsed = json.loads(args.features)
        except json.JSONDecodeError as exc:
            print(f"error: --features is not valid JSON: {exc}", file=sys.stderr)
            return 2
        if not isinstance(parsed, dict):
            print("error: --features must be a JSON object", file=sys.stderr)
            return 2
        features.update(parsed)

    redis_tags = list(MOCK_REDIS_TAGS)
    if args.redis_tags:
        try:
            parsed = json.loads(args.redis_tags)
        except json.JSONDecodeError as exc:
            print(f"error: --redis-tags is not valid JSON: {exc}", file=sys.stderr)
            return 2
        if not isinstance(parsed, list):
            print("error: --redis-tags must be a JSON array", file=sys.stderr)
            return 2
        redis_tags = [str(x) for x in parsed]

    signal_tags = list(MOCK_SIGNAL_TAGS)
    if args.signal_tags:
        try:
            parsed = json.loads(args.signal_tags)
        except json.JSONDecodeError as exc:
            print(f"error: --signal-tags is not valid JSON: {exc}", file=sys.stderr)
            return 2
        if not isinstance(parsed, list):
            print("error: --signal-tags must be a JSON array", file=sys.stderr)
            return 2
        signal_tags = [str(x) for x in parsed]

    debug_pack(pack, features, redis_tags, signal_tags)

    print("\n" + "=" * 72)
    print("Engine evaluation (evaluate_json_rules)")
    try:
        hits, tags, score_delta, pack_files = run_evaluation(
            pack,
            features,
            redis_tags,
            signal_tags,
            tenant_id=args.tenant_id,
            entity_id=args.entity_id,
        )
    except Exception as exc:
        print(f"ERROR: evaluate_json_rules failed: {exc}", file=sys.stderr)
        return 2

    meta = get_json_rule_engine_metadata()
    implied_decision = decision_from_score_delta(args.base_score, score_delta)

    print(f"engine: {meta.get('engine')} (fallback_active={meta.get('fallback_active')})")
    print(f"rule_hits: {hits}")
    print(f"tags: {tags}")
    print(f"score_delta: {score_delta}")
    print(f"contributing_packs: {pack_files}")
    print(f"implied_decision (~base {args.base_score} + delta): {implied_decision}")

    if not hits:
        print("\nNo rules fired — adjust MOCK_* / CLI inputs or rule when clauses.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
