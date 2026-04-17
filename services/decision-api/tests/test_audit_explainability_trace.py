"""Traceability: decision inference drivers must persist to audit and remain ordered."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest


@pytest.mark.asyncio
async def test_audit_endpoint_returns_ordered_driver_explain_and_reasons():
    trace_id = uuid4()
    inf_ctx = {
        "schema_version": "3",
        "calibration_profile": "default",
        "expected_calibration_version": 1,
        "confidence_tier": "medium",
        "confidence_tier_label": "Medium — mixed signals; review edge cases",
        "integrity_confidence": 0.55,
        "tamper_risk": 0.21,
        "network_trust": 0.72,
        "replay_risk": 0.0,
        "geo_consistency_risk": 0.12,
        "top_signals": ["sdk:vpn"],
        "driver_reasons": [
            "hostile_or_anonymous_network_path",
            "rule:velocity_guard",
            "ml_factor:HIGH_AMOUNT",
        ],
        "driver_explain": [
            {
                "reason": "hostile_or_anonymous_network_path",
                "category": "network",
                "label": "VPN, proxy, or hostile network path",
            },
            {
                "reason": "rule:velocity_guard",
                "category": "rules",
                "label": "Rule hit: velocity_guard",
            },
            {
                "reason": "ml_factor:HIGH_AMOUNT",
                "category": "ml",
                "label": "ML factor: HIGH_AMOUNT",
            },
        ],
        "colocation_risk": 0.0,
        "copresence_risk": 0.0,
        "impossible_travel_risk": 0.0,
        "velocity_events_5m": 1,
        "velocity_events_1h": 2,
        "velocity_events_24h": 3,
    }

    row = SimpleNamespace(
        trace_id=trace_id,
        tenant_id="t1",
        entity_id="u1",
        event_type="payment",
        decision="review",
        score=68.2,
        tags=["sdk:vpn"],
        rule_hits=["velocity_guard"],
        payload_snapshot={
            "inference_context": inf_ctx,
            "recommended_action": "step_up_mfa",
        },
        created_at=datetime.now(timezone.utc),
    )

    with patch("decision_api.main.init_db", new_callable=AsyncMock):
        with patch("decision_api.main.redis_tags") as mock_redis:
            mock_redis.connect = AsyncMock()
            mock_redis.close = AsyncMock()
            mock_redis._client = MagicMock()
            mock_redis.get_tags = AsyncMock(return_value=[])
            mock_redis.merge_tags = AsyncMock(return_value=[])
            mock_redis.set_cached_score = AsyncMock()
            mock_redis.store_nonce = AsyncMock()
            mock_redis.consume_nonce = AsyncMock(return_value=True)
            mock_redis.check_and_store_replay_signature = AsyncMock(return_value=False)
            with patch("decision_api.main.load_rules"):
                with patch("decision_api.main.agg_store") as mock_agg:
                    mock_agg._client = None
                    from decision_api.main import app, get_session

                    mock_session = AsyncMock()
                    exec_result = SimpleNamespace(scalar_one_or_none=lambda: row)
                    mock_session.execute = AsyncMock(return_value=exec_result)

                    async def _override():
                        yield mock_session

                    app.dependency_overrides[get_session] = _override
                    try:
                        transport = httpx.ASGITransport(app=app)
                        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
                            r = await c.get(f"/v1/audit/{trace_id}", params={"tenant_id": "t1"})
                    finally:
                        app.dependency_overrides.pop(get_session, None)

    assert r.status_code == 200
    data = r.json()
    got = data["inference_context"]
    assert got["driver_reasons"] == inf_ctx["driver_reasons"]
    assert [x["reason"] for x in got["driver_explain"]] == inf_ctx["driver_reasons"]
    assert got["driver_explain"][0]["category"] == "network"
    assert got["driver_explain"][1]["category"] == "rules"
    assert got["driver_explain"][2]["category"] == "ml"
