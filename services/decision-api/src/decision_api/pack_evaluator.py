"""Python JSON rule pack evaluation (fallback when Rust ``tarka_rule_engine`` is unavailable)."""

from __future__ import annotations

import logging
import time
from typing import Any

from tarka_core.engine_adapter import merge_features_with_resolved_from_packs
from tarka_core.internal_monitor import InternalMonitor

from decision_api.json_rules import (
    _MAX_RULES_PER_PACK,
    _pack_should_apply,
    evaluate_rule_when,
    evaluate_tag_rule_when,
)

MAX_EVAL_TIME_S = 0.05


class RuleEvaluationBudgetExceeded(RuntimeError):
    """Wall-clock budget exceeded (parity with Rust ``EvaluationBudgetExceeded``)."""

    def __init__(self, rule_id: str, *, phase: str = "rule") -> None:
        self.rule_id = rule_id
        self.phase = phase
        super().__init__(
            f"rule evaluation exceeded budget at {phase} (rule_id={rule_id})"
        )


def _expired(t0: float) -> bool:
    return (time.perf_counter() - t0) > MAX_EVAL_TIME_S


def _iter_eligible_packs(
    packs: list[dict[str, Any]], *, exclude_shadow: bool
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in packs:
        if p.get("version", 1) != 1:
            continue
        mode = p.get("mode", "active")
        if mode == "disabled":
            continue
        if exclude_shadow and mode == "shadow":
            continue
        out.append(p)
    return out


def _redis_tag_set(redis_tags: list[str]) -> set[str]:
    return {str(t) for t in redis_tags}


def _evaluate_one_pack(
    pack: dict[str, Any],
    features: dict[str, Any],
    redis_set: set[str],
    tenant_id: str,
    entity_id: str,
    evaluation_mode: str,
    t0: float,
) -> tuple[list[str], list[str], float, str | None, list[dict[str, Any]]]:
    hits: list[str] = []
    tags: list[str] = []
    delta = 0.0
    telemetry: list[dict[str, Any]] = []
    apply, _reason = _pack_should_apply(
        pack, tenant_id, entity_id, evaluation_mode=evaluation_mode
    )
    if not apply:
        return hits, tags, delta, None, telemetry

    pf_base = str(pack.get("_source_file") or "")
    rules = pack.get("rules") or []
    if isinstance(rules, list):
        for rule in rules[:_MAX_RULES_PER_PACK]:
            if not isinstance(rule, dict):
                continue
            rid = str(rule.get("id") or "unknown")
            if _expired(t0):
                raise RuleEvaluationBudgetExceeded(rid, phase="rule")
            if not evaluate_rule_when(
                rule, features, tenant_id=tenant_id, entity_id=entity_id
            ):
                continue
            hits.append(rid)
            for t in rule.get("tags") or []:
                if isinstance(t, str):
                    tags.append(t)
            try:
                delta += float(rule.get("score_delta") or 0.0)
            except (TypeError, ValueError) as exc:
                InternalMonitor.log_suppressed_error(
                    exc,
                    context="python_pack_rule_score_delta",
                    domain="fraud_decisioning",
                    level=logging.DEBUG,
                    rule_id=rid,
                )
            tel_row = {
                "pack_file": pf_base or "unknown",
                "rule_id": rid,
                "kind": "rule",
            }
            telemetry.append(tel_row)

    tag_rules = pack.get("tag_rules") or []
    if isinstance(tag_rules, list):
        for rule in tag_rules[:_MAX_RULES_PER_PACK]:
            if not isinstance(rule, dict):
                continue
            rid_raw = rule.get("id")
            tr_id = (
                "tagrule" if not rid_raw or str(rid_raw).strip() == "" else str(rid_raw)
            )
            if _expired(t0):
                raise RuleEvaluationBudgetExceeded(tr_id, phase="tag_rule")
            any_tag = rule.get("any_tag") or []
            if not isinstance(any_tag, list):
                continue
            if not evaluate_tag_rule_when(tr_id, any_tag, redis_set):
                continue
            rid = tr_id
            hits.append(rid)
            for t in rule.get("tags") or []:
                if isinstance(t, str):
                    tags.append(t)
            try:
                delta += float(rule.get("score_delta") or 0.0)
            except (TypeError, ValueError) as exc:
                InternalMonitor.log_suppressed_error(
                    exc,
                    context="python_pack_tag_rule_score_delta",
                    domain="fraud_decisioning",
                    level=logging.DEBUG,
                    rule_id=rid,
                )
            telemetry.append(
                {"pack_file": pf_base or "unknown", "rule_id": rid, "kind": "tag_rule"}
            )

    contributing: str | None = pf_base if hits else None
    return hits, tags, delta, contributing, telemetry


def evaluate_packs_python(
    packs: list[dict[str, Any]],
    features: dict[str, Any],
    redis_tags: list[str],
    tenant_id: str,
    entity_id: str,
    evaluation_mode: str,
    *,
    exclude_shadow: bool,
    fallback_active: bool = False,
) -> dict[str, Any]:
    tid = (tenant_id or "").strip() or "default"
    eid = (entity_id or "").strip() or "default"
    mode = (
        evaluation_mode
        if evaluation_mode in ("production", "simulation", "challenger")
        else "production"
    )
    base = dict(features) if isinstance(features, dict) else {}
    eligible = _iter_eligible_packs(packs, exclude_shadow=exclude_shadow)
    fmap = merge_features_with_resolved_from_packs(
        base, eligible, tenant_id=tid, entity_id=eid
    )
    redis_set = _redis_tag_set(redis_tags)

    hits: list[str] = []
    out_tags: list[str] = []
    delta = 0.0
    contributing_files: list[str] = []
    telemetry: list[dict[str, Any]] = []
    t0 = time.perf_counter()

    for pack in eligible:
        h, t, d, pf, tel = _evaluate_one_pack(
            pack,
            fmap,
            redis_set,
            tid,
            eid,
            mode,
            t0,
        )
        hits.extend(h)
        out_tags.extend(t)
        delta += d
        telemetry.extend(tel)
        if pf is not None:
            contributing_files.append(pf)

    contributing_sorted = sorted(set(contributing_files))
    return {
        "rule_hits": hits,
        "tags": out_tags,
        "score_delta": delta,
        "contributing_pack_files": contributing_sorted,
        "telemetry": telemetry,
        "metadata": {
            "fallback_active": fallback_active,
            "engine": "python",
        },
    }
