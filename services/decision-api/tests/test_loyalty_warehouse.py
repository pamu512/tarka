"""Loyalty warehouse pack fetch/validate."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from decision_api.loyalty_warehouse import (
    LoyaltyWarehouseError,
    fetch_loyalty_warehouse_pack,
    validate_loyalty_warehouse_pack,
)

_FIX = Path(__file__).resolve().parents[3] / "scripts" / "oss" / "fixtures"


def test_validate_complete_pack():
    body = json.loads((_FIX / "loyalty_warehouse_complete.json").read_text(encoding="utf-8"))
    pack = validate_loyalty_warehouse_pack(body)
    assert pack["gates_preview"]["order_eligible"] is True
    assert pack["gates_preview"]["order_decision_untouched"] is True


def test_validate_incomplete_never_eligible_true():
    body = json.loads((_FIX / "loyalty_warehouse_incomplete.json").read_text(encoding="utf-8"))
    pack = validate_loyalty_warehouse_pack(body)
    assert pack["gates_preview"]["order_eligible"] is None
    assert pack["gates_preview"]["status"] == "feeds_incomplete"


def test_fetch_via_mock_transport():
    body = json.loads((_FIX / "loyalty_warehouse_complete.json").read_text(encoding="utf-8"))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        pack = fetch_loyalty_warehouse_pack("http://warehouse.test/pack", client=client)
    assert pack["entity_id"] == "e-wh-ok"
    assert pack["gates_preview"]["order_eligible"] is True


def test_fetch_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        try:
            fetch_loyalty_warehouse_pack("http://warehouse.test/pack", client=client)
            raise AssertionError("expected LoyaltyWarehouseError")
        except LoyaltyWarehouseError as exc:
            assert "503" in str(exc)
