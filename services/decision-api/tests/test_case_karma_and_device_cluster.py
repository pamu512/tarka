"""Case karma features + host device_cluster writeback (Track F/C)."""

from __future__ import annotations

import httpx
import pytest

from decision_api.case_karma_features import (
    apply_case_karma_features,
    apply_case_karma_from_sources,
)
from decision_api.marketplace_features import apply_marketplace_features
from decision_api.partner_fusion import graph_writeback_hints
from decision_api.simulation_api import _eval_with_override_rules
from decision_api.vertical_packs import get_vertical_pack


def test_case_karma_from_metadata():
    feats: dict = {}
    apply_case_karma_from_sources(
        feats,
        {"repeat_refund_rate_30d": 0.5, "dispute_loss_rate_30d": 0.1, "seller_case_count_90d": 12},
    )
    assert feats["repeat_refund_high"] is True
    assert feats["case_karma_high"] is True
    assert feats["seller_case_volume_high"] is True


@pytest.mark.asyncio
async def test_case_karma_optional_case_api_mock(monkeypatch):
    monkeypatch.setenv("TARKA_CASE_API_URL", "http://case.test")
    monkeypatch.setenv("TARKA_CASE_API_KEY", "ck")

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/v1/entities/diner-1/karma" in str(request.url)
        return httpx.Response(
            200,
            json={"repeat_refund_rate_30d": 0.42, "dispute_loss_rate_30d": 0.05},
        )

    transport = httpx.MockTransport(handler)
    feats: dict = {}
    async with httpx.AsyncClient(transport=transport) as client:
        ev = await apply_case_karma_features(
            feats,
            payload=None,
            metadata={},
            http=client,
            tenant_id="t1",
            entity_id="diner-1",
        )
    assert feats["repeat_refund_high"] is True
    assert ev is not None and ev["source"] == "case_api"
    assert ev["live_claim_allowed"] is False


def test_device_cluster_writeback_host_supplied():
    feats: dict = {}
    apply_marketplace_features(
        feats, None, {"device_cluster_ids": ["clu-a", "clu-b", ""]}
    )
    assert feats["device_cluster_ids"] == ["clu-a", "clu-b"]
    hints = graph_writeback_hints(
        tenant_id="t1",
        entity_id="e1",
        transaction_id="tr1",
        tags=[],
        features=feats,
    )
    device_ids = {v["id"] for v in hints["vertices"] if v["label"] == "Device"}
    assert "cluster:clu-a" in device_ids
    assert "cluster:clu-b" in device_ids
    assert all(
        e["props"].get("source") == "host_device_cluster"
        for e in hints["edges"]
        if e["to"]["id"].startswith("cluster:")
    )


def test_food_and_marketplace_rules_fire_on_karma():
    feats = {"case_karma_high": True}
    for pack_id, rule_id in (
        ("food_delivery", "fd_case_karma_high"),
        ("marketplace", "mkt_case_karma_high"),
    ):
        pack = get_vertical_pack(pack_id)
        out = _eval_with_override_rules({"payload": feats}, pack["rules"])
        assert rule_id in out["rule_hits"]
