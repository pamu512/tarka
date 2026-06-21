"""Gate: live evaluation wire payloads are ``RiskDecision`` with business metrics stripped."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_ORCH) not in sys.path:
    sys.path.insert(0, str(_SRC_ORCH))

from routes.evaluate import finalize_live_evaluation_wire_payload  # noqa: E402
from schemas.domain_boundaries import RiskDecision  # noqa: E402


def test_finalize_live_evaluation_matches_risk_decision_shape() -> None:
    wire = finalize_live_evaluation_wire_payload(
        {
            "actions": ["FLAG"],
            "blocking_rule_id": None,
            "evaluation_trace": [{"rule_id": "velocity_ip", "matched": True}],
            "scores": {"graph_score": 0.42},
            "transaction_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        },
    )
    decision = RiskDecision.model_validate(wire)
    assert decision.actions == ["FLAG"]
    assert decision.scores["graph_score"] == pytest.approx(0.42)
    assert set(wire.keys()) == set(RiskDecision.model_fields.keys())


def test_finalize_live_evaluation_strips_business_pnl_keys(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.CRITICAL, logger="orchestrator.routes.evaluate")
    wire = finalize_live_evaluation_wire_payload(
        {
            "actions": ["ALLOW"],
            "evaluation_trace": [
                {
                    "rule_id": "r1",
                    "matched": True,
                    "estimated_revenue": 999.0,
                },
            ],
            "revenue_at_risk_cents": 500,
            "margin_impact_cents": -25,
        },
    )
    assert "revenue_at_risk_cents" not in wire
    assert "estimated_revenue" not in str(wire)
    assert any("orchestrator_architectural_boundary_violation" in r.message for r in caplog.records)


def test_finalize_live_evaluation_strips_financial_score_keys(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.CRITICAL, logger="orchestrator.routes.evaluate")
    wire = finalize_live_evaluation_wire_payload(
        {
            "actions": [],
            "scores": {"ltv_cents": 100, "graph_score": 0.5},
            "evaluation_trace": [],
        },
    )
    assert wire["scores"] == {"graph_score": 0.5}
    assert any("orchestrator_architectural_boundary_violation" in r.message for r in caplog.records)
