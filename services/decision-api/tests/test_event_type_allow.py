"""Allow-listed event_type on evaluate (seed ∪ env; overlay arrives later)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException


def test_pipeline_calls_require_allowed():
    pipeline = (
        Path(__file__).resolve().parents[1] / "src/decision_api/evaluate/pipeline.py"
    )
    text = pipeline.read_text(encoding="utf-8")
    assert "require_allowed_event_type" in text


def test_refund_rejected_without_env():
    from decision_api.event_type_gate import raise_if_event_type_not_allowed

    with pytest.raises(HTTPException) as exc:
        raise_if_event_type_not_allowed("refund")
    assert exc.value.status_code == 422
    detail = exc.value.detail
    assert detail["reason_codes"] == ["ingest_event_type_invalid"]


def test_refund_allowed_via_env(monkeypatch):
    from decision_api.event_type_gate import raise_if_event_type_not_allowed

    monkeypatch.setenv("TARKA_EVENT_TYPES", "refund")
    assert raise_if_event_type_not_allowed("refund") == "refund"
    assert raise_if_event_type_not_allowed("payment") == "payment"


def test_seed_types_always_allowed():
    from decision_api.event_type_gate import raise_if_event_type_not_allowed

    for name in ("login", "payment", "signup", "device", "session", "custom"):
        assert raise_if_event_type_not_allowed(name) == name
