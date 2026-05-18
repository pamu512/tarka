"""Unit tests for regional risk toggles (Prompt 187)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "src" / "integration_ingress" / "regional_risk_toggles.py"
_spec = importlib.util.spec_from_file_location("regional_risk_toggles", _MOD_PATH)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["regional_risk_toggles"] = _mod
_spec.loader.exec_module(_mod)


def test_payload_has_country_groups() -> None:
    payload = _mod.build_regional_risk_payload(tenant_id="demo")
    assert payload["country_groups"]
    assert payload["summary"]["sub_region_count"] >= 5


def test_blacklist_toggle() -> None:
    _mod._TOGGLE_STATE.clear()
    row = _mod.set_sub_region_blacklist(
        tenant_id="demo",
        sub_region_id="us-fl-miami",
        blacklisted=True,
        updated_by="test_analyst",
    )
    assert row is not None
    assert row["blacklisted"] is True
    payload = _mod.build_regional_risk_payload(tenant_id="demo")
    miami = next(r for r in payload["sub_regions"] if r["sub_region_id"] == "us-fl-miami")
    assert miami["blacklisted"] is True


def test_unknown_region_returns_none() -> None:
    assert _mod.set_sub_region_blacklist(tenant_id="demo", sub_region_id="xx-unknown", blacklisted=True) is None
