"""Trend agent: systemic gate, fail-closed LLM, triage + PENDING_VALIDATION drafts."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture()
def trend_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("TREND_AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TREND_AGENT_DB_NAME", "trend_test.sqlite3")
    from analytics import trend_store

    trend_store.reset_connection_for_tests()
    yield tmp_path
    trend_store.reset_connection_for_tests()


def test_seasonal_short_spike_resolves_systemic(trend_db: Path) -> None:
    from analytics.trend_agent import TrendAgent
    from analytics.trend_rag import compile_rag_matrix, try_resolve_systemic

    matrix = compile_rag_matrix(
        tenant_id="t1",
        entity_id="e1",
        window_rows=[
            {
                "metric_key": "sub_1min_velocity",
                "window": "sub_1min",
                "observed": 50,
                "baseline_mean": 5,
                "baseline_std": 2,
            },
            {
                "metric_key": "sub_1min_velocity",
                "window": "seasonal_historical_3y",
                "observed": 48,
                "baseline_mean": 45,
                "baseline_std": 5,
            },
        ],
    )
    disp, reason = try_resolve_systemic(matrix)
    assert disp == "RESOLVED_SYSTEMIC"
    assert "seasonal" in reason

    async def _run() -> dict:
        return await TrendAgent(skip_llm=True).run_evaluation_loop(
            tenant_id="t1",
            entity_id="e1",
            window_rows=[
                {
                    "metric_key": "sub_1min_velocity",
                    "window": "sub_1min",
                    "observed": 50,
                    "baseline_mean": 5,
                    "baseline_std": 2,
                },
                {
                    "metric_key": "sub_1min_velocity",
                    "window": "seasonal_historical_3y",
                    "observed": 48,
                    "baseline_mean": 45,
                    "baseline_std": 5,
                },
            ],
        )

    out = asyncio.run(_run())
    assert out["disposition"] == "RESOLVED_SYSTEMIC"
    assert out["triage_ticket_id"] is None
    assert out["draft_rule_id"] is None
    assert out["envelope"]["anomaly_detected"] is False


def test_unmanaged_high_z_escalates_and_drafts_pending(trend_db: Path) -> None:
    from analytics import trend_store
    from analytics.trend_agent import TrendAgent

    rows = [
        {
            "metric_key": "failed_auth_velocity",
            "window": "sub_1min",
            "observed": 100,
            "baseline_mean": 2,
            "baseline_std": 1,
        }
    ]

    async def _run() -> dict:
        return await TrendAgent(skip_llm=True).run_evaluation_loop(
            tenant_id="t1",
            entity_id="e-bad",
            window_rows=rows,
        )

    out = asyncio.run(_run())
    assert out["disposition"] == "ESCALATED"
    assert out["envelope"]["flag_for_hil_review"] is True
    assert out["triage_ticket_id"]
    assert out["draft_rule_id"]
    drafts = trend_store.list_pending_drafts(tenant_id="t1")
    assert len(drafts) == 1
    assert drafts[0]["status"] == "PENDING_VALIDATION"
    assert drafts[0]["rule_package"]["status"] == "PENDING_VALIDATION"
    assert drafts[0]["rule_package"].get("wasm_ready") is False
    assert drafts[0]["rule_package"].get("promotable") is False


def test_hil_override_closes_loop_next_iteration(trend_db: Path) -> None:
    from analytics.trend_agent import TrendAgent
    from analytics.trend_rag import HilOverride

    agent = TrendAgent(skip_llm=True)
    agent.apply_feedback_override(
        "t1",
        "e2",
        "ALLOW_SEASONAL_SPIKE",
        scope_key="day_of_year:340",
        analyst_rationale="Verified holiday surge",
    )

    rows = [
        {
            "metric_key": "sub_24h_velocity",
            "window": "sub_24h",
            "observed": 80,
            "baseline_mean": 10,
            "baseline_std": 2,
        }
    ]

    async def _run() -> dict:
        return await agent.run_evaluation_loop(
            tenant_id="t1",
            entity_id="e2",
            window_rows=rows,
            # HIL loaded from store inside loop when hil_overrides omitted
        )

    out = asyncio.run(_run())
    assert out["disposition"] == "RESOLVED_SYSTEMIC"
    assert out["triage_ticket_id"] is None


def test_llm_timeout_fail_closed_escalates(trend_db: Path) -> None:
    import httpx

    from analytics.trend_agent import TrendAgent

    class _Boom:
        async def complete_json(self, *, system: str, user: str) -> dict:
            raise httpx.ReadTimeout("simulated", request=httpx.Request("POST", "http://x"))

    rows = [
        {
            "metric_key": "sub_1min_velocity",
            "window": "sub_1min",
            "observed": 12,
            "baseline_mean": 8,
            "baseline_std": 1.5,
        }
    ]

    async def _run() -> dict:
        return await TrendAgent(llm=_Boom(), skip_llm=False).run_evaluation_loop(
            tenant_id="t1",
            entity_id="e3",
            window_rows=rows,
        )

    out = asyncio.run(_run())
    assert out["disposition"] == "ESCALATED"
    assert out["envelope"]["source"] == "timeout"
    assert out["envelope"]["flag_for_hil_review"] is True
    assert out["draft_rule_id"]


def test_openai_compatible_client_posts_chat_completions(trend_db: Path) -> None:
    import httpx

    from analytics.trend_agent import OpenAICompatibleJsonClient

    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode())
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "disposition": "MONITOR",
                                    "anomaly_detected": False,
                                    "flag_for_hil_review": False,
                                    "suggested_action": "MONITOR",
                                    "target_signature": {
                                        "metric_key": "sub_1min_velocity",
                                        "threshold_limit": 0,
                                        "scope": "entity",
                                    },
                                    "forensic_rationale": "ok",
                                }
                            )
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="http://llm.test")
    client = OpenAICompatibleJsonClient(
        base_url="http://llm.test/v1",
        model="any-model",
        api_key="sk-test",
        client=http,
    )

    async def _run() -> dict:
        try:
            return await client.complete_json(system="sys", user='{"rag":true}')
        finally:
            await http.aclose()

    out = asyncio.run(_run())
    assert out["disposition"] == "MONITOR"
    assert seen["url"].endswith("/v1/chat/completions")
    assert seen["body"]["model"] == "any-model"
    assert seen["auth"] == "Bearer sk-test"


def test_envelope_action_payload_shape(trend_db: Path) -> None:
    from analytics.trend_agent import TrendDecisionEnvelope, envelope_action_payload

    env = TrendDecisionEnvelope(
        disposition="ESCALATED",
        anomaly_detected=True,
        flag_for_hil_review=True,
        suggested_action="BLOCK",
        metric_key="sub_1min_velocity",
        threshold_limit=40,
        scope="entity",
        forensic_rationale="Z=9 burst",
        max_z_score=9.0,
        source="policy",
    )
    payload = envelope_action_payload(env)
    assert payload["suggested_action"] == "BLOCK"
    assert payload["target_signature"]["metric_key"] == "sub_1min_velocity"
    assert payload["target_signature"]["threshold_limit"] == 40
    assert payload["flag_for_hil_review"] is True
