"""Unit tests for promo abuse tracking (Prompt 180)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "src" / "integration_ingress" / "promo_abuse_tracking.py"
_spec = importlib.util.spec_from_file_location("promo_abuse_tracking", _MOD_PATH)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["promo_abuse_tracking"] = _mod
_spec.loader.exec_module(_mod)


def test_newuser50_default_count() -> None:
    payload = _mod.build_promo_abuse_payload(tenant_id="demo", coupon_code="NEWUSER50")
    assert payload["coupon_code"] == "NEWUSER50"
    assert payload["summary"]["unique_users"] == 47
    assert len(payload["users"]) == 47


def test_risk_elevated_when_over_warn() -> None:
    payload = _mod.build_promo_abuse_payload(tenant_id="demo", coupon_code="NEWUSER50")
    assert payload["summary"]["abuse_risk"] in ("elevated", "critical")
