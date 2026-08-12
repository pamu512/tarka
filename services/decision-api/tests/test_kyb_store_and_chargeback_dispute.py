"""Durable KYB store + chargeback → dispute bridge."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from decision_api.chargeback_dispute_bridge import (
    build_dispute_request,
    maybe_open_dispute_from_alert,
    should_open_dispute,
)
from decision_api.marketplace_kyb_store import MarketplaceKybStore
from decision_api.vertical_packs import get_vertical_pack
from decision_api.simulation_api import _eval_with_override_rules
from decision_api.marketplace_features import apply_marketplace_features


@pytest.mark.asyncio
async def test_kyb_store_memory_roundtrip():
    store = MarketplaceKybStore()
    store.clear_memory_for_tests()
    assert store.backend() == "memory"
    await store.put("t1", "s1", {"kyb_state": "collecting", "seller_gmv_30d": 9.0})
    row = await store.get("t1", "s1")
    assert row is not None
    assert row["kyb_state"] == "collecting"
    assert row["seller_id"] == "s1"


def test_should_open_dispute():
    assert not should_open_dispute({})
    assert should_open_dispute(
        {
            "features": {"chargeback_early_alert": True},
            "dispute_hint": {"dispute_type": "chargeback"},
        }
    )


def test_build_dispute_request():
    body = build_dispute_request(
        tenant_id="demo",
        normalized={
            "provider": "ethoca",
            "features": {
                "chargeback_early_alert": True,
                "transaction_id": "tx-1",
                "chargeback_alert_id": "E9",
                "chargeback_reason_code": "4853",
                "amount": 12.5,
                "currency": "usd",
            },
            "dispute_hint": {"transaction_id": "tx-1", "reason_code": "4853"},
        },
    )
    assert body["entity_id"] == "tx-1"
    assert body["trace_id"] == "cb-alert:E9"
    assert body["reason_code"] == "4853"
    assert body["amount"] == 12.5


@pytest.mark.asyncio
async def test_maybe_open_dispute_fail_soft_unconfigured(monkeypatch):
    monkeypatch.delenv("CASE_API_URL", raising=False)
    monkeypatch.delenv("TARKA_CASE_API_URL", raising=False)
    out = await maybe_open_dispute_from_alert(
        http=AsyncMock(),
        tenant_id="demo",
        normalized={
            "features": {"chargeback_early_alert": True},
            "dispute_hint": {},
        },
    )
    assert out["opened"] is False
    assert out["skipped_reason"] == "case_api_unconfigured"


@pytest.mark.asyncio
async def test_maybe_open_dispute_posts(monkeypatch):
    monkeypatch.setenv("CASE_API_URL", "http://case-api")
    mock_http = AsyncMock()
    resp = MagicMock()
    resp.status_code = 201
    resp.content = b'{"id":"d1"}'
    resp.json = MagicMock(return_value={"id": "d1"})
    mock_http.post = AsyncMock(return_value=resp)
    out = await maybe_open_dispute_from_alert(
        http=mock_http,
        tenant_id="demo",
        normalized={
            "provider": "verifi",
            "features": {
                "chargeback_early_alert": True,
                "transaction_id": "tx-2",
                "chargeback_alert_id": "V1",
            },
            "dispute_hint": {"transaction_id": "tx-2"},
        },
    )
    assert out["opened"] is True
    assert out["dispute"]["id"] == "d1"
    mock_http.post.assert_awaited_once()
    url = mock_http.post.await_args.args[0]
    assert url.endswith("/v1/disputes")


def test_food_delivery_pack_depth():
    pack = get_vertical_pack("food_delivery")
    assert pack is not None
    ids = {r["id"] for r in pack["rules"]}
    for need in (
        "fd_cancel_abuse_head",
        "fd_ftid_intake_mismatch",
        "fd_cross_role_same_device",
        "fd_refund_abuse_high",
        "fd_off_rail_payment",
    ):
        assert need in ids
    assert len(pack["rules"]) >= 10


def test_food_features_derive_heads_and_fire_rule():
    feats: dict = {}
    apply_marketplace_features(
        feats,
        {"cancel_heads": {"cancelled_offline": 0.9, "cancel_abuse": 0.1}},
        {"abuse_score": 0.85},
    )
    assert feats["cancelled_offline_high"] is True
    assert feats["refund_abuse_high"] is True
    pack = get_vertical_pack("food_delivery")
    assert pack is not None
    out = _eval_with_override_rules(
        {
            "payload": {
                **feats,
                "amount": 10,
                "account_age_days": 100,
                "transaction_count_24h": 1,
            }
        },
        pack["rules"],
    )
    assert "fd_cancelled_offline_head" in out["rule_hits"]
    assert "fd_refund_abuse_high" in out["rule_hits"]
