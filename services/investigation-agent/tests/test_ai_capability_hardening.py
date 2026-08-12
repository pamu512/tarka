"""Hardening: evaluate_entity_trend tool + richer case brief rendering."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_evaluate_entity_trend_requires_window_rows() -> None:
    from investigation_agent.tools import tool_evaluate_entity_trend

    http = AsyncMock()
    with patch("investigation_agent.tools.settings") as s:
        s.allowed_analysts = "*"
        s.decision_api_url = "http://decision.test"
        out = await tool_evaluate_entity_trend(
            http, "ten-a", "analyst-1", "ent-1", window_rows=None
        )
    assert out["error"] == "window_rows_required"
    http.post.assert_not_called()


@pytest.mark.asyncio
async def test_evaluate_entity_trend_posts_ops_evaluate() -> None:
    from investigation_agent.tools import tool_evaluate_entity_trend

    http = AsyncMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(
        return_value={
            "disposition": "ESCALATED",
            "draft_rule_id": "d1",
            "triage_ticket_id": "t1",
        }
    )
    http.post = AsyncMock(return_value=resp)
    rows = [
        {
            "metric_key": "sub_1min_velocity",
            "window": "sub_1min",
            "observed": 50,
            "baseline_mean": 5,
            "baseline_std": 1,
        }
    ]
    with patch("investigation_agent.tools.settings") as s:
        s.allowed_analysts = "*"
        s.decision_api_url = "http://decision.test"
        out = await tool_evaluate_entity_trend(
            http, "ten-a", "analyst-1", "ent-1", window_rows=rows, skip_llm=True
        )
    assert out["disposition"] == "ESCALATED"
    assert out["draft_rule_id"] == "d1"
    http.post.assert_awaited()
    args, kwargs = http.post.await_args
    assert args[0].endswith("/v1/ops/trend/evaluate")
    assert kwargs["json"]["window_rows"] == rows
    assert kwargs["json"]["skip_llm"] is True


def test_case_brief_includes_case_fields_and_nested_evidence() -> None:
    from investigation_agent.context_assembler import (
        assemble_context_snapshot,
        render_deterministic_case_brief,
    )

    case = {
        "id": "c-9",
        "tenant_id": "ten-a",
        "entity_id": "ent-9",
        "trace_id": "tr-9",
        "title": "Device hub",
        "status": "open",
        "priority": "high",
        "labels": ["ring", "device"],
        "decision_audit": {"action": "FLAG", "score": 88},
        "entity_velocity": {"events_1m": 12, "baseline_1m": 2},
    }
    snap = assemble_context_snapshot(
        tenant_id="ten-a",
        case_id="c-9",
        entity_id="ent-9",
        trace_id="tr-9",
        case_payload=case,
        decision_audit=case["decision_audit"],
        entity_velocity=case["entity_velocity"],
    )
    assert snap["freshness"]["case"] == "present"
    assert snap["freshness"]["decision_audit"] == "present"
    assert snap["freshness"]["entity_velocity"] == "present"
    brief = render_deterministic_case_brief(snap, case_payload=case)
    assert "Device hub" in brief
    assert "priority: `high`" in brief
    assert "decision_audit" in brief
    assert "llm" not in brief.lower() or "deterministic" in brief.lower()
