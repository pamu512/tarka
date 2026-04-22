from __future__ import annotations

"""Typology layer (OSS #34): aggregate rule outcomes + feature predicates into scored scenarios."""


import json
import logging
from pathlib import Path
from typing import Any

from decision_api.config import settings
from decision_api.json_rules import _match_condition
from decision_api.typology_predicate_registry import load_predicate_registry, predicate_when_by_id

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


def _resolve_feature_predicate(
    pred: dict[str, Any],
    registry: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """Return (condition dict for _match_condition, audit label) or (None, error)."""
    ref = str(pred.get("predicate_ref") or "").strip()
    if ref:
        when = predicate_when_by_id(registry, ref)
        if not when:
            return None, f"missing_predicate_ref:{ref}"
        cond = dict(when)
        return cond, f"ref:{ref}"
    cond = {k: pred[k] for k in ("field", "op", "value") if k in pred}
    if not cond.get("field"):
        return None, "invalid_inline_predicate"
    return cond, f"inline:{cond.get('field')}"


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
    registry = load_predicate_registry()
    reg_ver = int(registry.get("version") or 0)
    pin = data.get("predicate_registry_pin")
    pin_int = int(pin) if pin is not None else reg_ver
    pin_match = reg_ver == pin_int
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
            cond, label = _resolve_feature_predicate(pred, registry)
            if cond is None:
                continue
            if str(pred.get("predicate_ref") or "").strip() and not pin_match:
                continue
            try:
                if _match_condition(features, cond):
                    bonus = float(pred.get("bonus", 0))
                    score += bonus
                    val = pred.get("value", cond.get("value"))
                    feat_contrib.append(f"{label}:{cond.get('field')}:{cond.get('op')}:{val}")
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
                "dsl_version": int(data.get("dsl_version") or data.get("version") or 1),
                "predicate_registry": {
                    "registry_id": registry.get("registry_id"),
                    "version": reg_ver,
                    "pin": pin_int,
                    "pin_match": pin_match,
                },
            }
        )

    return out


def summarize_typologies(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Single dashboard row: worst breach + driver typology."""
    if not results:
        data = load_typology_definitions()
        reg = load_predicate_registry()
        rv = int(reg.get("version") or 0)
        pv = data.get("predicate_registry_pin")
        pin_int = int(pv) if pv is not None else rv
        return {
            "highest_breach": "pass",
            "recommended_disposition": "allow",
            "driver_typology_id": None,
            "dsl_version": int(data.get("dsl_version") or data.get("version") or 1),
            "predicate_registry": {
                "registry_id": reg.get("registry_id"),
                "version": rv,
                "pin": pin_int,
                "pin_match": rv == pin_int,
            },
        }
    alerts = [t for t in results if t.get("breach_level") == "alert"]
    warns = [t for t in results if t.get("breach_level") == "warning"]
    pr = (results[0] or {}).get("predicate_registry") or {}
    dv = (results[0] or {}).get("dsl_version")
    if alerts:
        best = max(alerts, key=lambda x: float(x.get("score") or 0))
        return {
            "highest_breach": "alert",
            "recommended_disposition": best.get("disposition", "deny"),
            "driver_typology_id": best.get("id"),
            "dsl_version": dv,
            "predicate_registry": pr,
        }
    if warns:
        best = max(warns, key=lambda x: float(x.get("score") or 0))
        return {
            "highest_breach": "warning",
            "recommended_disposition": best.get("disposition", "review"),
            "driver_typology_id": best.get("id"),
            "dsl_version": dv,
            "predicate_registry": pr,
        }
    return {
        "highest_breach": "pass",
        "recommended_disposition": "allow",
        "driver_typology_id": None,
        "dsl_version": dv,
        "predicate_registry": pr,
    }
