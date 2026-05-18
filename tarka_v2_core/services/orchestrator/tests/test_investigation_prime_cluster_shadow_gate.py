"""Gate: Knowledge Drop prime forwards graph + Duck velocity to Shadow and surfaces Cluster Analysis."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
for _p in (_SRC_ORCH, _SRC_INGESTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from orchestrator.analytics.duck_provider import DuckAnalyticsProvider  # noqa: E402
from orchestrator.main import create_app  # noqa: E402


def test_prime_shadow_receives_two_hop_and_duck_context(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _Cli:
        async def __aenter__(self) -> _Cli:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(
            self,
            url: str,
            json: dict[str, object] | None = None,
            headers: dict[str, str] | None = None,
            timeout: object | None = None,
        ) -> object:
            captured["url"] = url
            captured["body"] = json or {}
            tid = str((json or {})["transaction"]["entity_id"])  # type: ignore[index]
            return _ShadowOk(tid)

    class _ShadowOk:
        def __init__(self, tid: str) -> None:
            self._tid = tid
            self.status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "transaction_id": self._tid,
                "risk_score": 72.0,
                "is_fraud": True,
                "reasoning": ["synthetic gate"],
                "confidence_metrics": {"cluster": 0.9},
                "ai_reasoning": (
                    "**Cluster Analysis**: From ``two_hop_network`` the anchor shares devices with "
                    "blocked neighbors (see ``blocked_device_touch_count``). From ``duck_spend_velocity_30d``, "
                    "``spike_pct_vs_flat_baseline_2h`` is about 400% vs a flat 2h baseline—coordination risk is high."
                ),
            }

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _Cli())

    duck = DuckAnalyticsProvider()
    duck.load()
    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url="http://shadow.test",
        shadow_api_key="unit-test-token",
        duck_analytics_provider=duck,
    )
    raw = b"Chargeback paperwork for cust_99 attached.\n"
    with TestClient(app) as client:
        r = client.post(
            "/v1/investigation/prime",
            files={"file": ("dispute.txt", raw, "text/plain")},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "cust_99" in body["detected_ids"]
    assert body.get("cluster_analysis") is not None
    ai = str(body["cluster_analysis"].get("ai_reasoning", ""))
    assert "Cluster Analysis" in ai
    assert "two_hop_network" in ai.lower() or "blocked_device" in ai.lower()
    assert "duck" in ai.lower() or "spike" in ai.lower()

    gctx = (captured.get("body") or {}).get("graph_context")
    assert isinstance(gctx, dict)
    assert "two_hop_network" in gctx
    assert "duck_spend_velocity_30d" in gctx
    assert "cluster_analyst_instruction" in gctx
    assert "cust_99" in str(gctx.get("cluster_analyst_instruction", ""))
    assert str(captured.get("url", "")).endswith("/v1/analyze")
