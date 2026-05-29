"""Gate: risk vs business domain models stay strictly separated."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestrator.schemas.domain_boundaries import (
    BusinessImpact,
    RiskDecision,
    risk_decision_from_rule_engine_payload,
)


def test_risk_decision_accepts_policy_fields_only() -> None:
    decision = RiskDecision.model_validate(
        {
            "scores": {"graph_score": 0.82, "velocity_score": 0.15},
            "actions": ["FLAG"],
            "blocking_rule_id": None,
            "evaluation_trace": [{"rule_id": "velocity_ip", "matched": True}],
        },
    )
    assert decision.actions == ["FLAG"]
    assert decision.scores["graph_score"] == 0.82


def test_risk_decision_rejects_financial_score_keys() -> None:
    with pytest.raises(ValidationError, match="financial/business metric"):
        RiskDecision.model_validate(
            {
                "scores": {"ltv_cents": 100},
                "actions": [],
                "evaluation_trace": [],
            },
        )


def test_risk_decision_rejects_business_fields_on_payload_lift() -> None:
    with pytest.raises(ValueError, match="BusinessImpact"):
        risk_decision_from_rule_engine_payload(
            {
                "actions": [],
                "ltv_cents": 500,
                "evaluation_trace": [],
            },
        )


def test_business_impact_requires_cents_fields() -> None:
    impact = BusinessImpact.model_validate(
        {
            "ltv_cents": 10_000,
            "margin_impact_cents": -250,
            "revenue_at_risk_cents": 1_500,
        },
    )
    assert impact.revenue_at_risk_cents == 1_500


def test_domains_cannot_share_inheritance() -> None:
    with pytest.raises(TypeError, match="cannot inherit from (risk|business) domain"):

        class _Bad(RiskDecision, BusinessImpact):  # type: ignore[misc, valid-type]
            pass
