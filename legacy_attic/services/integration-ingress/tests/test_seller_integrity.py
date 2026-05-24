"""Unit tests for seller integrity scores (Prompt 182)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MOD_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "integration_ingress" / "seller_integrity.py"
)
_spec = importlib.util.spec_from_file_location("seller_integrity", _MOD_PATH)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["seller_integrity"] = _mod
_spec.loader.exec_module(_mod)


def test_payload_structure() -> None:
    payload = _mod.build_seller_integrity_payload(tenant_id="demo", limit=25)
    assert payload["tenant_id"] == "demo"
    assert len(payload["sellers"]) == 25
    assert payload["summary"]["seller_count"] == 25
    first = payload["sellers"][0]
    assert "review_to_delivery_ratio" in first
    assert "integrity_score" in first


def test_reviews_without_deliveries_critical() -> None:
    score, tier, signals = _mod._score_seller(successful_deliveries=0, review_count=10)
    assert tier == "critical"
    assert score < 20
    assert "reviews_without_deliveries" in signals


def test_healthy_ratio_trusted() -> None:
    score, tier, _ = _mod._score_seller(successful_deliveries=200, review_count=70)
    assert tier == "trusted"
    assert score >= 85
