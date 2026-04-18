"""Typology layer (OSS #34): aggregate rule outcomes + feature predicates into scored scenarios."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from decision_api.config import settings
from decision_api.json_rules import _match_condition

log = logging.getLogger(__name__)

_DEFINITIONS: dict[str, Any] | None = None


def load_typology_definitions() -> dict[str, Any]:
    global _DEFINITIONS
    if _DEFINITIONS is not None:
        return _DEFINITIONS
    base = Path(settings.rules_path)
    path = base / "typology_definitions_v1.json"
    if not path.is_file():
        log.warning("typology definitions not found: %s", path)
        _DEFINITIONS = {"version": 1, "typologies": []}
        return _DEFINITIONS
    try:
        _DEFINITIONS = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("failed to load typology definitions: %s", e)
        _DEFINITIONS = {"version": 1, "typologies": []}
    return _DEFINITIONS


def reload_typology_definitions() -> None:
    global _DEFINITIONS
    _DEFINITIONS = None
    load_typology_definitions()


def _breach_level(score: float, warn: float, alert: float) -> str:
    if score >= alert:
        return "alert"
    if score >= warn:
        return "warning"
    return "pass"


def evaluate_typologies(
    rule_hits: list[str],
    features: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return one result dict per configured typology (audit + optional UI)."""
    data = load_typology_definitions()
    hits_set = {str(h) for h in rule_hits}
    out: list[dict[str, Any]] = []

    for spec in data.get("typologies") or []:
        tid = str(spec.get("id") or "")
        if not tid:
            continue
        w = float(spec.get("weight_per_rule_hit") or 1.0)
        members = [str(x) for x in (spec.get("member_rule_ids") or [])]
        contributing_rules = [m for m in members if m in hits_set]
        score = len(contributing_rules) * w

        feat_contrib: list[str] = []
        for pred in spec.get("feature_predicates") or []:
            if not isinstance(pred, dict):
                continue
            cond = {k: pred[k] for k in ("field", "op", "value") if k in pred}
            if not cond.get("field"):
                continue
            try:
                if _match_condition(features, cond):
                    bonus = float(pred.get("bonus", 0))
                    score += bonus
                    feat_contrib.append(f"{cond.get('field')}:{cond.get('op')}:{pred.get('value')}")
            except Exception:
                continue

        thr = spec.get("breach_thresholds") or {}
        warn = float(thr.get("warning", 50))
        alert = float(thr.get("alert", 80))
        level = _breach_level(score, warn, alert)
        disp_map = spec.get("disposition") or {"pass": "allow", "warning": "review", "alert": "deny"}
        disposition = str(disp_map.get(level) or "review")

        out.append(
            {
                "id": tid,
                "label": str(spec.get("label") or tid),
                "score": round(score, 4),
                "breach_level": level,
                "breach_thresholds": {"warning": warn, "alert": alert},
                "contributing_rule_hits": contributing_rules,
                "contributing_feature_predicates": feat_contrib,
                "disposition": disposition,
            }
        )

    return out


def summarize_typologies(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Single dashboard row: worst breach + driver typology."""
    if not results:
        return {
            "highest_breach": "pass",
            "recommended_disposition": "allow",
            "driver_typology_id": None,
        }
    alerts = [t for t in results if t.get("breach_level") == "alert"]
    warns = [t for t in results if t.get("breach_level") == "warning"]
    if alerts:
        best = max(alerts, key=lambda x: float(x.get("score") or 0))
        return {
            "highest_breach": "alert",
            "recommended_disposition": best.get("disposition", "deny"),
            "driver_typology_id": best.get("id"),
        }
    if warns:
        best = max(warns, key=lambda x: float(x.get("score") or 0))
        return {
            "highest_breach": "warning",
            "recommended_disposition": best.get("disposition", "review"),
            "driver_typology_id": best.get("id"),
        }
    return {
        "highest_breach": "pass",
        "recommended_disposition": "allow",
        "driver_typology_id": None,
    }
