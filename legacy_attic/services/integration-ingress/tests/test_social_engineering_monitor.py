"""Unit tests for social engineering monitor (Prompt 184)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "src" / "integration_ingress" / "social_engineering_monitor.py"
_spec = importlib.util.spec_from_file_location("social_engineering_monitor", _MOD_PATH)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["social_engineering_monitor"] = _mod
_spec.loader.exec_module(_mod)


def test_flags_credential_burst_after_high_value_listing() -> None:
    payload = _mod.build_social_engineering_payload(tenant_id="demo", limit=30)
    flagged = [a for a in payload["accounts"] if a["is_social_engineering_flag"]]
    assert flagged
    row = flagged[0]
    assert "social_engineering_credential_burst" in row["signals"]
    assert row["minutes_listing_to_email_change"] is not None
    assert row["minutes_listing_to_password_change"] is not None
    assert row["minutes_listing_to_email_change"] <= payload["config"]["credential_change_window_minutes"]


def test_low_value_listing_not_flagged() -> None:
    cfg = _mod.get_social_engineering_config("demo")
    flagged, signals = _mod._is_flagged(
        listing_value_usd=400,
        minutes_email_after_listing=2.0,
        minutes_password_after_listing=3.0,
        cfg=cfg,
    )
    assert not flagged
    assert signals == []


def test_config_patch() -> None:
    _mod.update_social_engineering_config(tenant_id="cfg_test", high_value_listing_usd=10000)
    cfg = _mod.get_social_engineering_config("cfg_test")
    assert cfg["high_value_listing_usd"] == 10000
