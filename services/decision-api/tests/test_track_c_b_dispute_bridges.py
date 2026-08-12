"""Track C3 dispute evidence + Track B sibling posture / KYB file backend."""

from __future__ import annotations

from pathlib import Path

import pytest

from decision_api.chargeback_alert_webhook import normalize_chargeback_alert_payload
from decision_api.chargeback_dispute_bridge import maybe_open_dispute_from_alert
from decision_api.dispute_representment import apply_representment_features
from decision_api.marketplace_kyb_store import MarketplaceKybStore
from decision_api.sibling_bridge_posture import load_sibling_bridge_ops_posture
from unittest.mock import AsyncMock, MagicMock


def test_dispute_hint_includes_evidence_pdf_fields():
    out = normalize_chargeback_alert_payload(
        "ethoca",
        {
            "alert_id": "E1",
            "transaction_id": "tx-9",
            "reason_code": "4853",
            "amount": 40,
            "has_pod": True,
            "has_tracking": False,
            "evidence_pdf_urls": ["https://host.example/pod.pdf"],
        },
    )
    hint = out["dispute_hint"]
    assert hint["has_pod"] is True
    assert hint["has_tracking"] is False
    assert hint["evidence_pdf_urls"] == ["https://host.example/pod.pdf"]
    assert hint["live_claim_allowed"] is False
    reproc = hint["evaluate_reprocess"]
    assert reproc["dispute_evidence"]["has_pod"] is True
    assert "evidence_pdf_urls" in reproc["dispute_evidence"]
    assert "evaluate_reprocess" not in reproc["dispute_hint"]


@pytest.mark.asyncio
async def test_dispute_id_attached_and_representment_from_reprocess(monkeypatch):
    monkeypatch.setenv("CASE_API_URL", "http://case-api")
    out = normalize_chargeback_alert_payload(
        "verifi",
        {
            "alert_id": "V2",
            "transaction_id": "tx-22",
            "reason_code": "4853",
            "has_pod": False,
            "has_tracking": False,
            "has_chat": False,
            "evidence_pdf_url": "https://host.example/weak.pdf",
        },
    )
    mock_http = AsyncMock()
    resp = MagicMock()
    resp.status_code = 201
    resp.content = b'{"id":"disp-99"}'
    resp.json = MagicMock(return_value={"id": "disp-99"})
    mock_http.post = AsyncMock(return_value=resp)
    bridge = await maybe_open_dispute_from_alert(
        http=mock_http, tenant_id="demo", normalized=out
    )
    assert bridge["opened"] is True
    assert bridge["dispute_id"] == "disp-99"
    assert out["dispute_hint"]["dispute_id"] == "disp-99"
    assert out["dispute_hint"]["evaluate_reprocess"]["dispute_id"] == "disp-99"

    feats: dict = {}
    apply_representment_features(feats, None, out["dispute_hint"]["evaluate_reprocess"])
    assert feats.get("representment_weak") is True


def test_sibling_bridge_posture_shape():
    body = load_sibling_bridge_ops_posture()
    assert body["schema_id"] == "tarka.sibling_bridge_ops/v1"
    assert body["live_claim_allowed"] is False
    ids = {b["bridge_id"] for b in body["bridges"]}
    assert ids == {"loyalty_abuse", "refund_abuse", "offline_cancel"}
    for b in body["bridges"]:
        assert "configured" in b
        assert "circuit_open" in b
        assert "blockers" in b


@pytest.mark.asyncio
async def test_kyb_file_backend_roundtrip(tmp_path: Path):
    path = tmp_path / "kyb.json"
    store = MarketplaceKybStore(file_path=path)
    assert store.backend() == "file"
    await store.put("t1", "seller-a", {"kyb_state": "verified", "seller_gmv_30d": 1.0})
    assert path.is_file()
    store2 = MarketplaceKybStore(file_path=path)
    row = await store2.get("t1", "seller-a")
    assert row is not None
    assert row["kyb_state"] == "verified"
