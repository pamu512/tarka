from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any

from decision_api.config import settings

"""Challenge / escalation policy templates (Epic D) — extends recommended_action hints."""
log = logging.getLogger(__name__)

_policies: dict[str, dict[str, Any]] | None = None


def load_challenge_policies(*, force: bool = False) -> None:
    """Load JSON templates from ``{rules_path}/challenge_policies/*.json``."""
    global _policies
    if _policies is not None and not force:
        return
    _policies = {}
    base = Path(settings.rules_path)
    d = base / "challenge_policies"
    if not d.is_dir():
        log.info("challenge_policies directory missing: %s", d)
        return
    for f in sorted(d.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            pid = str(data.get("policy_id", "")).strip()
            if not pid:
                log.warning("challenge policy file %s missing policy_id", f.name)
                continue
            if int(data.get("version", 1)) < 1:
                continue
            _policies[pid] = data
        except Exception as e:
            log.warning("challenge policy %s: %s", f.name, e)
    log.info("Loaded %d challenge policy template(s) from %s", len(_policies), d)


def list_policy_ids() -> list[str]:
    load_challenge_policies()
    return sorted(_policies.keys()) if _policies else []


def get_policy_summaries() -> list[dict[str, Any]]:
    """Public summaries for GET /v1/challenge-policies."""
    load_challenge_policies()
    if not _policies:
        return []
    rows: list[dict[str, Any]] = []
    for pid in sorted(_policies.keys()):
        p = _policies[pid]
        rows.append(
            {
                "policy_id": pid,
                "version": int(p.get("version", 1)),
                "description": str(p.get("description", "")),
            }
        )
    return rows


def _safe_float(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _matches_when(
    when: dict[str, Any],
    decision: str,
    inf_ctx: dict[str, Any],
    tags: list[str],
    payload: dict[str, Any],
) -> bool:
    if not when:
        return True
    if "decision" in when and str(when["decision"]) != decision:
        return False
    if "confidence_tier" in when and str(when["confidence_tier"]) != str(inf_ctx.get("confidence_tier", "")):
        return False
    for key, inf_key in (
        ("min_tamper_risk", "tamper_risk"),
        ("min_replay_risk", "replay_risk"),
        ("min_impossible_travel_risk", "impossible_travel_risk"),
        ("min_geo_consistency_risk", "geo_consistency_risk"),
    ):
        if key in when:
            if _safe_float(inf_ctx.get(inf_key)) < _safe_float(when[key]):
                return False
    if "min_amount" in when:
        if _safe_float(payload.get("amount")) < _safe_float(when["min_amount"]):
            return False
    if "max_amount" in when:
        if _safe_float(payload.get("amount")) > _safe_float(when["max_amount"]):
            return False
    if "has_tag" in when:
        needle = str(when["has_tag"])
        if not any(needle in str(t) for t in tags):
            return False
    return True


def apply_challenge_policy(
    policy_id: str | None,
    base_action: str | None,
    decision: str,
    inf_ctx: dict[str, Any],
    tags: list[str],
    payload: dict[str, Any],
) -> tuple[str | None, dict[str, Any]]:
    """
    Apply template rules on top of ``derive_recommended_action`` output (``base_action``).

    Returns (final_recommended_action, metadata for audit/UI).
    """
    load_challenge_policies()
    requested_pid = (policy_id or "").strip()
    default_pid = (settings.challenge_policy_default or "default_v1").strip()
    pid = requested_pid or default_pid
    meta: dict[str, Any] = {
        "policy_id": pid,
        "requested_policy_id": requested_pid or None,
        "default_policy_id": default_pid,
        "matched_rule_id": None,
        "rule_index": None,
        "escalation_ladder": [],
        "effective_source": "requested" if requested_pid else "default",
    }
    if _policies is None or not _policies:
        meta["note"] = "no_policies_loaded"
        return base_action, meta

    policy = _policies.get(pid)
    if not policy:
        log.warning("unknown challenge_policy_id=%r", pid)
        fallback = _policies.get(default_pid)
        if fallback:
            policy = fallback
            meta["error"] = "unknown_policy_fallback_default"
            meta["effective_source"] = "fallback_default"
        else:
            meta["error"] = "unknown_policy"
            return base_action, meta

    meta["policy_id"] = str(policy.get("policy_id", pid))
    meta["escalation_ladder"] = list(policy.get("escalation_ladder", []))

    rules = policy.get("rules") or []
    for idx, rule in enumerate(rules):
        when = rule.get("when") or {}
        if not isinstance(when, dict):
            continue
        if _matches_when(when, decision, inf_ctx, tags, payload):
            action = rule.get("recommended_action")
            meta["matched_rule_id"] = rule.get("id")
            meta["rule_index"] = idx
            return (str(action) if action is not None else None), meta

    default_mode = policy.get("default", "use_base_engine")
    if default_mode == "use_base_engine":
        return base_action, meta
    if isinstance(default_mode, str) and default_mode not in ("use_base_engine",):
        return default_mode, meta
    return base_action, meta
