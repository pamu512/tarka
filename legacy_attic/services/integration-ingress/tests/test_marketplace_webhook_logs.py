"""Unit tests for marketplace webhook log helpers (Prompt 175)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_MOD_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "integration_ingress"
    / "marketplace_webhook_logs.py"
)
_spec = importlib.util.spec_from_file_location("marketplace_webhook_logs", _MOD_PATH)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


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
