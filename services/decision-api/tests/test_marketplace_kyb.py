"""Marketplace INFORM-shaped KYB workflow + gate."""

from __future__ import annotations

import pytest

from decision_api.marketplace_kyb import (
    apply_transition,
    empty_seller_record,
    evaluate_kyb_gate,
)


def test_high_volume_unverified_suspends():
    gate = evaluate_kyb_gate(
        kyb_state="unverified",
        seller_gmv_30d=12_000,
        high_volume_threshold=5000,
    )
    assert gate["suspend_sales"] is True
    assert "action:suspend_sales" in gate["tags"]
    assert "risk:kyb_unverified_high_volume" in gate["tags"]
    assert gate["score_delta"] >= 30


def test_disclosed_vendor_ok():
    gate = evaluate_kyb_gate(
        kyb_state="disclosed",
        seller_gmv_30d=20_000,
        vendor_verified=True,
        disclosure_complete=True,
    )
    assert gate["suspend_sales"] is False
    assert "kyb:ok" in gate["tags"]
    assert "kyb:vendor_verified" in gate["tags"]


def test_sla_breach_suspends():
    gate = evaluate_kyb_gate(
        kyb_state="collecting",
        seller_gmv_30d=100,
        collect_started_at="2020-01-01T00:00:00+00:00",
        sla_hours=72,
    )
    assert "risk:kyb_sla_breach" in gate["tags"]
    assert gate["suspend_sales"] is True


def test_illegal_transition_rejected():
    row = empty_seller_record(tenant_id="t1", seller_id="s1")
    with pytest.raises(ValueError, match="illegal_kyb_transition"):
        apply_transition(row, "disclosed")


def test_collect_to_pending_ok():
    row = empty_seller_record(tenant_id="t1", seller_id="s1")
    row = apply_transition(row, "collecting", reason="threshold")
    row = apply_transition(row, "pending_vendor", reason="docs_submitted")
    assert row["kyb_state"] == "pending_vendor"
    assert len(row["history"]) == 2


def test_suspicious_activity_suspends_unverified():
    from decision_api.marketplace_kyb import apply_suspicious_activity_report

    row = empty_seller_record(tenant_id="t1", seller_id="s1")
    row = apply_suspicious_activity_report(
        row, report_id="r1", category="counterfeit", narrative="fake goods"
    )
    assert row["kyb_state"] == "suspended"
    assert len(row["suspicious_reports"]) == 1
    gate = evaluate_kyb_gate(kyb_state=row["kyb_state"], seller_gmv_30d=100)
    assert gate["suspend_sales"] is True


@pytest.mark.asyncio
async def test_kyb_api_gate_and_transition(monkeypatch):
    monkeypatch.setenv("API_KEYS", "test-key")
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("FEATURE_SERVICE_URL", "")

    from unittest.mock import AsyncMock, MagicMock, patch

    import httpx

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
            mock_redis.get_tenant_flags = AsyncMock(return_value={})
            with patch("decision_api.main.load_rules"):
                with patch("decision_api.main.agg_store") as mock_agg:
                    mock_agg._client = None
                    from decision_api.main import app
                    from decision_api.marketplace_kyb_store import kyb_store

                    kyb_store.clear_memory_for_tests()
                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(
                        transport=transport, base_url="http://testserver"
                    ) as c:
                        c.headers.update({"x-api-key": "test-key"})
                        r = await c.post(
                            "/v1/marketplace/kyb/gate",
                            json={
                                "tenant_id": "demo",
                                "seller_id": "seller-1",
                                "kyb_state": "unverified",
                                "seller_gmv_30d": 9000,
                            },
                        )
                        assert r.status_code == 200
                        assert r.json()["gate"]["suspend_sales"] is True

                        r2 = await c.post(
                            "/v1/marketplace/kyb/sellers/transition",
                            json={
                                "tenant_id": "demo",
                                "seller_id": "seller-1",
                                "to_state": "collecting",
                                "seller_gmv_30d": 9000,
                                "reason": "start",
                            },
                        )
                        assert r2.status_code == 200
                        assert r2.json()["seller"]["kyb_state"] == "collecting"
