"""Unit tests for evaluate body construction."""

from __future__ import annotations

from tarka_test.request_builder import build_evaluate_body


def test_input_signals_merge() -> None:
    body = build_evaluate_body(
        {
            "id": "x",
            "input_signals": {"risk.score": 0.9},
            "request": {"tenant_id": "t1"},
        },
        {"default_platform": "ios", "default_device_id": "dev-1"},
    )
    assert body["tenant_id"] == "t1"
    dc = body["device_context"]
    assert dc["device_id"] == "dev-1"
    assert dc["platform"] == "ios"
    assert dc["signals"]["risk.score"] == 0.9
