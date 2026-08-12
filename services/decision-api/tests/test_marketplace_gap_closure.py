"""Marketplace gap-closure: pack posture, aliases, connectors, sibling bridges."""

from __future__ import annotations

import pytest

from decision_api.offline_cancel_bridge import map_cancel_response, should_invoke_cancel_bridge
from decision_api.refund_abuse_bridge import map_refund_response, should_invoke_refund_bridge
from decision_api.vendors.plugins.chargeback_alert import ChargebackAlertVendorPlugin
from decision_api.vendors.plugins.chargeback_alert import ChargebackAlertCredentials
from decision_api.vendors.plugins.identity_kyb import (
    IdentityKybCredentials,
    IdentityKybVendorPlugin,
)
from decision_api.vertical_packs import (
    get_vertical_pack,
    list_vertical_packs,
    load_vertical_pack_ops_posture,
    resolve_pack_name,
)


def test_marketplace_pack_has_kyb_ftid_chargeback_rules():
    pack = get_vertical_pack("marketplace")
    assert pack is not None
    ids = {r["id"] for r in pack["rules"]}
    for need in (
        "mkt_kyb_unverified_high_gmv",
        "mkt_ftid_intake_mismatch",
        "mkt_chargeback_early_alert",
        "mkt_listing_brand_hit",
        "mkt_off_rail_payment",
    ):
        assert need in ids
    assert pack["posture"]["business_type"] == "marketplace_goods"
    assert "identity_kyb" in pack["posture"]["required_connectors"]
    assert "action:suspend_sales" in pack["posture"]["host_actions"]


def test_aliases_and_e_hailing():
    assert resolve_pack_name("marketplace_goods") == "marketplace"
    assert resolve_pack_name("last_mile") == "logistics"
    eh = get_vertical_pack("e_hailing")
    assert eh is not None
    assert len(eh["rules"]) >= 5
    assert "e_hailing" in list_vertical_packs()


def test_pack_ops_posture_marketplace_first():
    out = load_vertical_pack_ops_posture(
        connector_families={
            "device": {"live_claim_allowed": False},
            "identity_kyb": {"live_claim_allowed": False},
            "chargeback_alert": {"live_claim_allowed": False},
        }
    )
    assert out["schema_id"] == "tarka.vertical_pack_ops_posture/v1"
    assert out["priority_note"].startswith("marketplace-first")
    mkt = next(p for p in out["packs"] if p["pack_id"] == "marketplace")
    assert mkt["pack_ready"] is False
    assert any("connector_not_live" in b for b in mkt["connector_blockers"])


def test_refund_bridge_maps_hold():
    assert should_invoke_refund_bridge(metadata={"checkpoint": "refund"})
    res = map_refund_response(
        {"refund_effect": "hold", "abuse_score": 0.9, "reason_codes": ["repeat"]}
    )
    assert "action:refund_hold" in res.tags
    assert "risk:refund_burst" in res.tags
    ev = res.evidence()
    assert ev is not None
    assert ev["advisory"] is True


def test_cancel_bridge_maps_heads():
    assert should_invoke_cancel_bridge(metadata={"checkpoint": "cancel"})
    res = map_cancel_response(
        {"heads": {"cancelled_offline": 0.8, "selective_theft": 0.2}}
    )
    assert "risk:courier_spoof" in res.tags
    assert "cancel:head:cancelled_offline" in res.tags


def test_chargeback_plugin_parses_alert():
    plugin = ChargebackAlertVendorPlugin(
        ChargebackAlertCredentials(
            api_key="test-key-xxxx", base_url="https://cb.example.com"
        )
    )
    signals = plugin._signals_from_body(
        '{"alert": true, "severity": "high", "alert_id": "a1"}', 200, None
    )
    assert len(signals) == 1
    assert signals[0].score_0_100 >= 85
    assert "chargeback_alert:early_alert" in signals[0].reason_codes


def test_chargeback_plugin_404_is_no_alert():
    plugin = ChargebackAlertVendorPlugin(
        ChargebackAlertCredentials(
            api_key="test-key-xxxx", base_url="https://cb.example.com"
        )
    )
    signals = plugin._signals_from_body("", 404, None)
    assert signals[0].score_0_100 == 0.0
    assert "chargeback_alert:no_alert" in signals[0].reason_codes


def test_chargeback_webhook_normalizes_ethoca():
    from decision_api.chargeback_alert_webhook import normalize_chargeback_alert_payload

    out = normalize_chargeback_alert_payload(
        "ethoca",
        {
            "ethoca_id": "E-1",
            "arn": "tx-99",
            "severity": "high",
            "reason_code": "4853",
            "amount": 42.5,
        },
    )
    assert out["features"]["chargeback_early_alert"] is True
    assert out["features"]["transaction_id"] == "tx-99"
    assert "action:dispute_open" in out["tags"]
    assert out["dispute_hint"]["reason_code"] == "4853"


def test_identity_kyb_plugin_verified():
    plugin = IdentityKybVendorPlugin(
        IdentityKybCredentials(
            api_key="test-key-xxxx", base_url="https://kyb.example.com"
        )
    )
    signals = plugin._signals_from_body('{"status": "approved"}', 200, None)
    assert signals[0].score_0_100 <= 10
    assert "identity_kyb:verified" in signals[0].reason_codes


@pytest.mark.asyncio
async def test_ops_posture_endpoints(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock, patch

    import httpx

    monkeypatch.setenv("API_KEYS", "test-key")
    monkeypatch.delenv("ALLOW_INSECURE_NO_AUTH", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("FEATURE_SERVICE_URL", "")

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

                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(
                        transport=transport, base_url="http://testserver"
                    ) as c:
                        c.headers.update({"x-api-key": "test-key"})
                        r = await c.get("/v1/ops/connector-posture")
                        assert r.status_code == 200
                        body = r.json()
                        assert body["schema_id"] == "tarka.connector_ops_posture/v1"
                        assert "chargeback_alert" in body["families"]

                        r2 = await c.get("/v1/ops/vertical-pack-posture")
                        assert r2.status_code == 200
                        packs = r2.json()["packs"]
                        assert any(p["pack_id"] == "marketplace" for p in packs)
