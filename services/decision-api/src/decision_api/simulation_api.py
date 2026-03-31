"""Simulation API router — synthetic data generation and replay analysis."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from decision_api.config import settings
from decision_api.json_rules import evaluate_json_rules
from decision_api.simulator import (
    SCENARIO_TEMPLATES,
    SyntheticProfile,
    analyze_simulation,
    generate_scenario,
)

log = logging.getLogger(__name__)

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
        rule_hits, rule_tags, score_delta = evaluate_json_rules(features, [])
        score = max(0.0, min(100.0, 10.0 + score_delta))

        if score >= settings.deny_threshold:
            decision = "deny"
        elif score >= settings.review_threshold:
            decision = "review"
        else:
            decision = "allow"

        decisions.append({
            "decision": decision,
            "score": score,
            "rule_hits": rule_hits,
            "tags": rule_tags,
        })

    result = analyze_simulation(events, decisions)
    return {
        "result": result.model_dump(),
        "sample_events": events[:10],
        "sample_decisions": decisions[:10],
    }


class ABTestRequest(BaseModel):
    scenario: str = "baseline"
    custom_profile: SyntheticProfile | None = None
    rule_set_a: list[dict] = Field(default_factory=list, description="Override rules for set A (empty = production)")
    rule_set_b: list[dict] = Field(default_factory=list, description="Override rules for set B")


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

    def _eval_with_rules(event: dict, override_rules: list[dict]) -> dict:
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
            hits, tags, delta = evaluate_json_rules(features, [])
            score = max(0.0, min(100.0, 10.0 + delta))

        if score >= settings.deny_threshold:
            decision = "deny"
        elif score >= settings.review_threshold:
            decision = "review"
        else:
            decision = "allow"
        return {"decision": decision, "score": score, "rule_hits": hits}

    decisions_a = [_eval_with_rules(e, body.rule_set_a) for e in events]
    decisions_b = [_eval_with_rules(e, body.rule_set_b) for e in events]

    result_a = analyze_simulation(events, decisions_a)
    result_b = analyze_simulation(events, decisions_b)

    return {
        "scenario": profile.name,
        "total_events": len(events),
        "set_a": result_a.model_dump(),
        "set_b": result_b.model_dump(),
        "comparison": {
            "precision_delta": round(result_b.precision - result_a.precision, 4),
            "recall_delta": round(result_b.recall - result_a.recall, 4),
            "f1_delta": round(result_b.f1_score - result_a.f1_score, 4),
            "fp_delta": result_b.false_positives - result_a.false_positives,
            "fn_delta": result_b.false_negatives - result_a.false_negatives,
        },
    }
