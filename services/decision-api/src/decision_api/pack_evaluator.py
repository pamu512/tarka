"""Python JSON rule pack evaluation (fallback when Rust ``tarka_rule_engine`` is unavailable)."""

from __future__ import annotations

import logging
import time
from typing import Any

from pydantic import TypeAdapter
from tarka_core.engine_adapter import merge_features_with_resolved_from_packs
from tarka_core.internal_monitor import InternalMonitor

from decision_api.ast_evaluator import evaluate_json_ast
from decision_api.ast_models import JsonAstNode, enforce_ast_limits
from decision_api.json_rules import (
    _MAX_CONDITIONS_PER_RULE,
    _MAX_FIELD_LEN,
    _MAX_RULES_PER_PACK,
    _match_condition,
    _pack_should_apply,
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


def _rule_when_matches(
    rule: dict[str, Any],
    merged_features: dict[str, Any],
    tenant_id: str,
    entity_id: str,
) -> bool:
    """Evaluate ``when`` / ``when_ast`` against ``merged_features``.

    ``merged_features`` must already include ``custom_signal`` resolutions from
    :func:`merge_features_with_resolved_from_packs` (parity with Rust feeding one map into ``eval_ast``).
    """
    _ = tenant_id, entity_id
    when = rule.get("when")
    raw_ast = rule.get("when_ast")
    has_flat = isinstance(when, list) and len(when) > 0
    has_ast = raw_ast is not None

    if has_flat and has_ast:
        return False

    if has_ast:
        try:
            node = TypeAdapter(JsonAstNode).validate_python(raw_ast)
            enforce_ast_limits(node)
        except Exception:
            return False
        return evaluate_json_ast(node, merged_features)

    if not has_flat:
        return False

    if len(when) > _MAX_CONDITIONS_PER_RULE:
        return False

    for c in when:
        if not isinstance(c, dict):
            return False
        fld = c.get("field")
        if not fld or len(str(fld)) > _MAX_FIELD_LEN:
            return False
    return all(_match_condition(merged_features, c) for c in when)


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
            if not _rule_when_matches(rule, features, tenant_id, entity_id):
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
            need = {str(t) for t in any_tag if isinstance(t, str)}
            if not need or not any(t in redis_set for t in need):
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
