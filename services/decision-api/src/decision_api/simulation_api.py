from __future__ import annotations
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from decision_api.config import settings
from decision_api.experiment_api import append_experiment_record
from decision_api.json_rules import evaluate_json_rules
from decision_api.simulator import (
"""Simulation API router — synthetic data generation and replay analysis."""
    SCENARIO_TEMPLATES,
    SyntheticProfile,
    analyze_simulation,
    generate_scenario,
)
from decision_api.vertical_packs import get_vertical_pack

log = logging.getLogger(__name__)

_MIN_SIM_N = 200

router = APIRouter(prefix="/v1/simulation", tags=["simulation"])


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


@router.post("/run")
async def run_simulation(body: RunSimulationRequest, request: Request):
    """Generate synthetic data and evaluate through the rules engine."""
    if body.custom_profile:
        profile = body.custom_profile
    elif body.scenario in SCENARIO_TEMPLATES:
        profile = SCENARIO_TEMPLATES[body.scenario]
    else:
        raise HTTPException(400, f"Unknown scenario '{body.scenario}'. Available: {list(SCENARIO_TEMPLATES.keys())}")

    events = generate_scenario(profile)
    decisions = []

    for event in events:
        features = dict(event.get("payload", {}))
        rule_hits, rule_tags, score_delta, _pack_files = evaluate_json_rules(
            features,
            [],
            evaluation_mode="simulation",
        )
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
            "notes": [
                "Use fixed scenario seeds and frozen rule packs when comparing runs.",
                "Large metric swings with the same profile often mean insufficient sample size or non-deterministic rules.",
                "Do not treat simulation precision/recall as production KPIs without labeled production holdouts.",
            ],
        },
    }


class ABTestRequest(BaseModel):
    scenario: str = "baseline"
    custom_profile: SyntheticProfile | None = None
    rule_set_a: list[dict] = Field(default_factory=list, description="Override rules for set A (empty = production)")
    rule_set_b: list[dict] = Field(default_factory=list, description="Override rules for set B")


def _eval_with_override_rules(event: dict[str, Any], override_rules: list[dict[str, Any]]) -> dict[str, Any]:
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
        hits, tags, delta, _pack_files = evaluate_json_rules(features, [], evaluation_mode="simulation")
        score = max(0.0, min(100.0, 10.0 + delta))

    if score >= settings.deny_threshold:
        decision = "deny"
    elif score >= settings.review_threshold:
        decision = "review"
    else:
        decision = "allow"
    return {"decision": decision, "score": score, "rule_hits": hits}


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
    )

    return {
        "scenario": profile.name,
        "total_events": n,
        "set_a": result_a.model_dump(),
        "set_b": result_b.model_dump(),
        "experiment_guardrails": {
            "minimum_recommended_events": _MIN_SIM_N,
            "low_sample_warning": n < _MIN_SIM_N,
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


@router.post("/benchmark/vertical")
async def benchmark_vertical_pack(body: VerticalBenchmarkRequest):
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
    baseline = [_eval_with_override_rules(e, []) for e in events]
    vertical = [_eval_with_override_rules(e, vertical_pack.get("rules", [])) for e in events]
    result_base = analyze_simulation(events, baseline)
    result_vertical = analyze_simulation(events, vertical)
    n = len(events)
    append_experiment_record(
        "vertical_benchmark",
        scenario=body.scenario,
        vertical=body.vertical.lower(),
        events_evaluated=n,
        notes="POST /v1/simulation/benchmark/vertical",
    )

    return {
        "scenario": profile.name,
        "vertical": body.vertical.lower(),
        "baseline": result_base.model_dump(),
        "vertical_pack": result_vertical.model_dump(),
        "experiment_guardrails": {
            "minimum_recommended_events": _MIN_SIM_N,
            "low_sample_warning": n < _MIN_SIM_N,
        },
        "delta": {
            "precision": round(result_vertical.precision - result_base.precision, 4),
            "recall": round(result_vertical.recall - result_base.recall, 4),
            "f1_score": round(result_vertical.f1_score - result_base.f1_score, 4),
            "score_separation": round(result_vertical.score_separation - result_base.score_separation, 2),
            "false_positives": result_vertical.false_positives - result_base.false_positives,
            "false_negatives": result_vertical.false_negatives - result_base.false_negatives,
        },
    }
