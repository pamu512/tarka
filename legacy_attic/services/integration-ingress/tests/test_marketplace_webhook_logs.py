"""Unit tests for marketplace webhook log helpers (Prompt 175)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from integration_ingress import marketplace_webhook_logs as _mod


def test_preview_truncates() -> None:
    p = _mod._preview({"signal": "block", "x": "y" * 500}, limit=50)
    assert len(p) <= 50
    assert "block" in p


def test_row_to_dict_shape() -> None:
    class Row:
        id = "00000000-0000-0000-0000-000000000001"
        tenant_id = "demo"
        signal = "block"
        decision = "BLOCK"
        entity_id = "e1"
        user_id = "u1"
        trace_id = "t1"
        callback_url = "https://example.com/hook"
        status = "delivered"
        http_status = 200
        attempt_count = 1
        latency_ms = 12.5
        payload_preview = "{}"
        last_error = None
        created_at = None
        delivered_at = None
        attempts_json = []
        payload_json = {}

    d = _mod._row_to_dict(Row())
    assert d["signal"] == "block"
    assert d["status"] == "delivered"


def test_delivery_failed_constant_is_generic() -> None:
    assert _mod._DELIVERY_FAILED == "delivery failed"
    assert "Exception" not in _mod._DELIVERY_FAILED


def test_record_marketplace_block_webhook() -> None:
    import asyncio

    session = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    row = asyncio.run(
        _mod.record_marketplace_block_webhook(
            session,
            tenant_id="demo",
            callback_url="https://example.com/hook",
            payload={"signal": "block", "entity_id": "e1"},
            entity_id="e1",
            trace_id="trace-1",
        ),
    )
    assert row["tenant_id"] == "demo"
    assert row["signal"] == "block"
    session.add.assert_called_once()
    session.commit.assert_awaited_once()
