from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from decision_api.config import settings
from decision_api.experiment_api import append_experiment_record
from decision_api.json_rules import evaluate_json_rules
from decision_api.rust_rule_engine_exceptions import (
    RustRuleEngineCircuitOpenError,
    RustRuleEngineInvocationFailed,
)
from decision_api.simulator import (
    SCENARIO_TEMPLATES,
    SyntheticProfile,
    analyze_simulation,
    generate_scenario,
)
from decision_api.vertical_packs import evaluate_kill_criteria, get_vertical_pack

"""Simulation API router — synthetic data generation and replay analysis."""

log = logging.getLogger(__name__)

_MIN_SIM_N = 200

router = APIRouter(prefix="/v1/simulation", tags=["simulation"])


def _reject_underpowered(n: int, allow: bool) -> None:
    if n < _MIN_SIM_N and not allow:
        raise HTTPException(
            status_code=422,
            detail={
                "reason_code": "SIMULATION_UNDERPOWERED",
                "message": (
                    f"Simulation has {n} events; minimum recommended is {_MIN_SIM_N}. "
                    "Pass allow_underpowered=true to override (results must not be treated as KPIs)."
                ),
                "events_evaluated": n,
                "minimum_recommended_events": _MIN_SIM_N,
                "holdout_required": True,
            },
        )


@router.get("/scenarios")
async def list_scenarios():
    """List available built-in simulation scenarios."""
    return {
        "scenarios": {
            name: {
                "name": p.name,
                "total_events": p.total_events,
                "fraud_rate": p.fraud_rate,
                "description": _scenario_descriptions.get(name, ""),
            }
            for name, p in SCENARIO_TEMPLATES.items()
        }
    }


_scenario_descriptions = {
    "baseline": "Standard transaction mix with 5% fraud rate",
    "high_fraud": "Elevated 15% fraud rate stress test",
    "bot_attack": "Coordinated bot-driven attack with 30% fraud, heavy automation signals",
    "account_takeover": "ATO pattern with VPN usage and velocity spikes",
    "money_mule": "Money mule network with high amounts from new accounts",
}


class RunSimulationRequest(BaseModel):
    scenario: str = "baseline"
    custom_profile: SyntheticProfile | None = None
    evaluate_rules: bool = True
    include_ml: bool = False
    allow_underpowered: bool = Field(
        default=False,
        description="If false (default), reject runs below minimum_recommended_events.",
    )


@router.post("/run")
async def run_simulation(body: RunSimulationRequest, request: Request):
    """Generate synthetic data and evaluate through the rules engine."""
    if body.custom_profile:
        profile = body.custom_profile
    elif body.scenario in SCENARIO_TEMPLATES:
        profile = SCENARIO_TEMPLATES[body.scenario]
    else:
        raise HTTPException(
            400,
            f"Unknown scenario '{body.scenario}'. Available: {list(SCENARIO_TEMPLATES.keys())}",
        )

    events = generate_scenario(profile)
    _reject_underpowered(len(events), body.allow_underpowered)
    decisions = []

    for event in events:
        features = dict(event.get("payload", {}))
        try:
            rule_hits, rule_tags, score_delta, _pack_files = evaluate_json_rules(
                features,
                [],
                evaluation_mode="simulation",
            )
        except (RustRuleEngineCircuitOpenError, RustRuleEngineInvocationFailed) as e:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "rust_rule_engine_unavailable",
                    "message": "Simulation requires the JSON rule engine; Rust FFI circuit open or invocation failed.",
                    "exc_type": type(e).__name__,
                },
            ) from e
        score = max(0.0, min(100.0, 10.0 + score_delta))

        if score >= settings.deny_threshold:
            decision = "deny"
        elif score >= settings.review_threshold:
            decision = "review"
        else:
            decision = "allow"

        decisions.append(
            {
                "decision": decision,
                "score": score,
                "rule_hits": rule_hits,
                "tags": rule_tags,
            }
        )

    result = analyze_simulation(events, decisions)
    n = len(events)
    append_experiment_record(
        "simulation_run",
        scenario=body.scenario,
        events_evaluated=n,
        notes="POST /v1/simulation/run",
        meta={"include_ml": body.include_ml},
        allow_underpowered=body.allow_underpowered,
        minimum_recommended_events=_MIN_SIM_N,
    )
    low_n = n < _MIN_SIM_N
    return {
        "result": result.model_dump(),
        "sample_events": events[:10],
        "sample_decisions": decisions[:10],
        "experiment_guardrails": {
            "events_evaluated": n,
            "minimum_recommended_events": _MIN_SIM_N,
            "low_sample_warning": low_n,
            "underpowered": low_n,
            "holdout_ok": (not low_n) or body.allow_underpowered,
            "kpi_eligible": not low_n,
            "notes": [
                "Use fixed scenario seeds and frozen rule packs when comparing runs.",
                "Large metric swings with the same profile often mean insufficient sample size or non-deterministic rules.",
                "Do not treat simulation precision/recall as production KPIs without labeled production holdouts.",
                "kpi_eligible is false when underpowered even if allow_underpowered was set.",
            ],
        },
    }


class ABTestRequest(BaseModel):
    scenario: str = "baseline"
    custom_profile: SyntheticProfile | None = None
    rule_set_a: list[dict] = Field(
        default_factory=list,
        description="Override rules for set A (empty = production)",
    )
    rule_set_b: list[dict] = Field(
        default_factory=list, description="Override rules for set B"
    )
    allow_underpowered: bool = False


def _decision_from_score(score: float) -> str:
    if score >= settings.deny_threshold:
        return "deny"
    if score >= settings.review_threshold:
        return "review"
    return "allow"


def _eval_vertical_benchmark_baseline(event: dict[str, Any]) -> dict[str, Any]:
    """Score-floor baseline for vertical pack benchmarks (no RULES_PATH packs).

    ``_eval_with_override_rules(e, [])`` means production rules (AB-test semantics);
    vertical smoke compares pack-only rules against an unscoped floor so deltas stay
    stable as the default rules directory grows.
    """
    score = 10.0
    return {
        "decision": _decision_from_score(score),
        "score": score,
        "rule_hits": [],
        "tags": [],
    }


def _eval_with_override_rules(
    event: dict[str, Any], override_rules: list[dict[str, Any]]
) -> dict[str, Any]:
    features = dict(event.get("payload", {}))
    if override_rules:
        from decision_api.json_rules import _match_condition

        hits: list[str] = []
        tags: list[str] = []
        delta = 0.0
        for rule in override_rules:
            conditions = rule.get("when", [])
            if conditions and all(_match_condition(features, c) for c in conditions):
                hits.append(rule.get("id", "override"))
                tags.extend(rule.get("tags", []))
                delta += float(rule.get("score_delta", 0))
        score = max(0.0, min(100.0, 10.0 + delta))
    else:
        try:
            hits, tags, delta, _pack_files = evaluate_json_rules(
                features, [], evaluation_mode="simulation"
            )
        except (RustRuleEngineCircuitOpenError, RustRuleEngineInvocationFailed) as e:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "rust_rule_engine_unavailable",
                    "exc_type": type(e).__name__,
                },
            ) from e
        score = max(0.0, min(100.0, 10.0 + delta))

    if score >= settings.deny_threshold:
        decision = "deny"
    elif score >= settings.review_threshold:
        decision = "review"
    else:
        decision = "allow"
    return {
        "decision": decision,
        "score": score,
        "rule_hits": hits,
        "tags": list(dict.fromkeys(tags)),
    }


@router.post("/ab-test")
async def ab_test(body: ABTestRequest):
    """Run the same synthetic data through two different rule sets and compare."""
    if body.custom_profile:
        profile = body.custom_profile
    elif body.scenario in SCENARIO_TEMPLATES:
        profile = SCENARIO_TEMPLATES[body.scenario]
    else:
        raise HTTPException(400, f"Unknown scenario: {body.scenario}")

    events = generate_scenario(profile)
    _reject_underpowered(len(events), body.allow_underpowered)

    decisions_a = [_eval_with_override_rules(e, body.rule_set_a) for e in events]
    decisions_b = [_eval_with_override_rules(e, body.rule_set_b) for e in events]

    result_a = analyze_simulation(events, decisions_a)
    result_b = analyze_simulation(events, decisions_b)
    n = len(events)
    append_experiment_record(
        "ab_test",
        scenario=body.scenario,
        events_evaluated=n,
        notes="POST /v1/simulation/ab-test",
        allow_underpowered=body.allow_underpowered,
        minimum_recommended_events=_MIN_SIM_N,
    )

    return {
        "scenario": profile.name,
        "total_events": n,
        "set_a": result_a.model_dump(),
        "set_b": result_b.model_dump(),
        "experiment_guardrails": {
            "minimum_recommended_events": _MIN_SIM_N,
            "low_sample_warning": n < _MIN_SIM_N,
            "underpowered": n < _MIN_SIM_N,
            "holdout_ok": (n >= _MIN_SIM_N) or body.allow_underpowered,
            "kpi_eligible": n >= _MIN_SIM_N,
        },
        "comparison": {
            "precision_delta": round(result_b.precision - result_a.precision, 4),
            "recall_delta": round(result_b.recall - result_a.recall, 4),
            "f1_delta": round(result_b.f1_score - result_a.f1_score, 4),
            "fp_delta": result_b.false_positives - result_a.false_positives,
            "fn_delta": result_b.false_negatives - result_a.false_negatives,
        },
    }


class VerticalBenchmarkRequest(BaseModel):
    scenario: str = "baseline"
    vertical: str = "fintech"
    custom_profile: SyntheticProfile | None = None
    seed: int = Field(
        42,
        description="RNG seed for reproducible simulation events (publishable scorecards)",
    )
    allow_underpowered: bool = False


@router.post("/benchmark/vertical")
async def benchmark_vertical_pack(body: VerticalBenchmarkRequest):
    import random

    random.seed(body.seed)
    if body.custom_profile:
        profile = body.custom_profile
    elif body.scenario in SCENARIO_TEMPLATES:
        profile = SCENARIO_TEMPLATES[body.scenario]
    else:
        raise HTTPException(400, f"Unknown scenario: {body.scenario}")

    vertical_pack = get_vertical_pack(body.vertical)
    if not vertical_pack:
        raise HTTPException(404, f"Unknown vertical pack: {body.vertical}")

    events = generate_scenario(profile)
    _reject_underpowered(len(events), body.allow_underpowered)
    baseline = [_eval_vertical_benchmark_baseline(e) for e in events]
    vertical = [
        _eval_with_override_rules(e, vertical_pack.get("rules", [])) for e in events
    ]
    result_base = analyze_simulation(events, baseline)
    result_vertical = analyze_simulation(events, vertical)
    n = len(events)
    append_experiment_record(
        "vertical_benchmark",
        scenario=body.scenario,
        vertical=body.vertical.lower(),
        events_evaluated=n,
        notes="POST /v1/simulation/benchmark/vertical",
        allow_underpowered=body.allow_underpowered,
        minimum_recommended_events=_MIN_SIM_N,
    )

    vert_metrics = result_vertical.model_dump()
    promote = evaluate_kill_criteria(
        vert_metrics,
        vertical_pack.get("kill_criteria"),
        events_evaluated=n,
    )
    if n < _MIN_SIM_N:
        promote = {
            **promote,
            "promote_allowed": False,
            "blockers": list(promote.get("blockers") or []) + ["low_sample_warning"],
        }
    from decision_api.backtest_promote_gate import fixture_holdout_promote_gate

    fixture_gate = fixture_holdout_promote_gate(vertical=body.vertical.lower())
    if not fixture_gate.get("waived") and not fixture_gate.get("promote_allowed"):
        promote = {
            **promote,
            "promote_allowed": False,
            "blockers": list(promote.get("blockers") or [])
            + [
                f"fixture_holdout:{b}"
                for b in (fixture_gate.get("blockers") or ["blocked"])
            ],
            "fixture_holdout_gate": fixture_gate,
        }
    else:
        promote = {
            **promote,
            "fixture_holdout_gate": fixture_gate,
            "promote_live_claim_allowed": False,
            "promote_fixture_claim_allowed": bool(
                fixture_gate.get("promote_fixture_claim_allowed")
            ),
        }

    return {
        "scenario": profile.name,
        "vertical": body.vertical.lower(),
        "seed": body.seed,
        "events_evaluated": n,
        "baseline": result_base.model_dump(),
        "vertical_pack": vert_metrics,
        "experiment_guardrails": {
            "minimum_recommended_events": _MIN_SIM_N,
            "low_sample_warning": n < _MIN_SIM_N,
            "underpowered": n < _MIN_SIM_N,
            "holdout_ok": (n >= _MIN_SIM_N) or body.allow_underpowered,
            "kpi_eligible": n >= _MIN_SIM_N,
        },
        "promote_gate": promote,
        "delta": {
            "precision": round(result_vertical.precision - result_base.precision, 4),
            "recall": round(result_vertical.recall - result_base.recall, 4),
            "f1_score": round(result_vertical.f1_score - result_base.f1_score, 4),
            "score_separation": round(
                result_vertical.score_separation - result_base.score_separation, 2
            ),
            "false_positives": result_vertical.false_positives
            - result_base.false_positives,
            "false_negatives": result_vertical.false_negatives
            - result_base.false_negatives,
        },
    }
