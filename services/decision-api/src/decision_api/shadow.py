"""Shadow mode — evaluate alternative rule sets against live traffic without affecting decisions.

Shadow rules are evaluated in parallel with production rules. Results are logged
for comparison but do NOT affect the actual decision returned to the caller.
"""

import json
import logging
import os
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("decision-api.shadow")

_shadow_rules_path = os.environ.get("SHADOW_RULES_PATH", "")
_shadow_enabled = bool(_shadow_rules_path)
_shadow_packs: list[dict] = []


def is_shadow_enabled() -> bool:
    return _shadow_enabled


def load_shadow_rules() -> None:
    global _shadow_packs, _shadow_enabled
    if not _shadow_rules_path or not os.path.isdir(_shadow_rules_path):
        _shadow_enabled = False
        return
    _shadow_packs = []
    for fname in sorted(os.listdir(_shadow_rules_path)):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(_shadow_rules_path, fname)) as f:
                pack = json.load(f)
            _shadow_packs.append(pack)
        except Exception as e:
            log.warning("Failed to load shadow rule pack %s: %s", fname, e)
    _shadow_enabled = len(_shadow_packs) > 0
    log.info(
        "Loaded %d shadow rule packs from %s", len(_shadow_packs), _shadow_rules_path
    )


def evaluate_shadow(features: dict[str, Any], tags: list[str]) -> dict[str, Any] | None:
    """Evaluate shadow rules against the same features. Returns comparison result or None if disabled."""
    from decision_api.json_rules import evaluate_adhoc_packs_json, get_shadow_packs

    shadow_mode_packs = get_shadow_packs()
    has_file_packs = _shadow_enabled and bool(_shadow_packs)
    has_mode_packs = bool(shadow_mode_packs)

    if not has_file_packs and not has_mode_packs:
        return None

    packs: list[dict] = []
    if has_file_packs:
        packs.extend(_shadow_packs)
    packs.extend(shadow_mode_packs)
    all_hits, all_tags, total_delta, _pf = evaluate_adhoc_packs_json(
        packs,
        features,
        tags,
        evaluation_mode="simulation",
        record_telemetry=False,
    )

    shadow_score = max(0.0, min(100.0, 10.0 + total_delta))

    if shadow_score >= 80:
        shadow_decision = "deny"
    elif shadow_score >= 50:
        shadow_decision = "review"
    else:
        shadow_decision = "allow"

    return {
        "shadow_decision": shadow_decision,
        "shadow_score": shadow_score,
        "shadow_rule_hits": all_hits,
        "shadow_tags": all_tags,
    }


# ---------- observation log ----------

_observation_log: deque = deque(maxlen=10000)
_obs_lock = threading.Lock()


def record_observation(
    trace_id: str,
    production: dict[str, Any],
    shadow: dict[str, Any],
) -> None:
    """Record a shadow vs production observation for analysis."""
    with _obs_lock:
        _observation_log.append(
            {
                "trace_id": trace_id,
                "production_decision": production.get("decision"),
                "production_score": production.get("score"),
                "shadow_decision": shadow.get("shadow_decision"),
                "shadow_score": shadow.get("shadow_score"),
                "diverged": production.get("decision") != shadow.get("shadow_decision"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )


def get_observations(limit: int = 100) -> list[dict[str, Any]]:
    """Get recent shadow observations."""
    with _obs_lock:
        return list(_observation_log)[-limit:]


def get_observation_stats() -> dict[str, Any]:
    """Aggregate stats from the observation log."""
    with _obs_lock:
        obs = list(_observation_log)

    if not obs:
        return {"total": 0}

    total = len(obs)
    diverged = sum(1 for o in obs if o.get("diverged"))
    prod_decisions: dict[str, int] = {}
    shadow_decisions: dict[str, int] = {}
    for o in obs:
        pd = o.get("production_decision", "unknown")
        sd = o.get("shadow_decision", "unknown")
        prod_decisions[pd] = prod_decisions.get(pd, 0) + 1
        shadow_decisions[sd] = shadow_decisions.get(sd, 0) + 1

    tp = sum(
        1
        for o in obs
        if o.get("production_decision") == "deny" and o.get("shadow_decision") == "deny"
    )
    fp = sum(
        1
        for o in obs
        if o.get("production_decision") != "deny" and o.get("shadow_decision") == "deny"
    )
    fn = sum(
        1
        for o in obs
        if o.get("production_decision") == "deny" and o.get("shadow_decision") != "deny"
    )
    tn = sum(
        1
        for o in obs
        if o.get("production_decision") != "deny" and o.get("shadow_decision") != "deny"
    )

    score_diffs = [o.get("shadow_score", 0) - o.get("production_score", 0) for o in obs]
    avg_score_delta = sum(score_diffs) / len(score_diffs) if score_diffs else 0.0
    sorted_diffs = sorted(score_diffs)
    p95_idx = min(int(len(sorted_diffs) * 0.95), len(sorted_diffs) - 1)
    score_delta_p95 = sorted_diffs[p95_idx] if sorted_diffs else 0.0

    return {
        "total": total,
        "diverged": diverged,
        "divergence_rate": round(diverged / total * 100, 1),
        "production_distribution": prod_decisions,
        "shadow_distribution": shadow_decisions,
        "confusion_matrix": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "avg_score_delta": round(avg_score_delta, 2),
        "score_delta_p95": round(score_delta_p95, 2),
    }
