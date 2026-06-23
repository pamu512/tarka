"""Unit tests for payout delay automation (Prompt 183)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MOD_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "integration_ingress"
    / "payout_delay_automation.py"
)
_spec = importlib.util.spec_from_file_location("payout_delay_automation", _MOD_PATH)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["payout_delay_automation"] = _mod
_spec.loader.exec_module(_mod)


def test_high_mule_score_triggers_hold() -> None:
    _mod._RELEASED_PAYOUT_IDS.clear()
    _mod.update_payout_delay_config(
        tenant_id="demo", automation_enabled=True, mule_score_hold_threshold=50
    )
    payload = _mod.build_payout_delay_payload(tenant_id="demo", limit=20)
    held = [p for p in payload["payouts"] if p["status"] == "held"]
    assert held
    assert held[0]["hold_reason"] is not None
    assert held[0]["held_by"] == "payout_delay_automation"


def test_release_clears_hold() -> None:
    payload = _mod.build_payout_delay_payload(tenant_id="demo", limit=5)
    pid = payload["payouts"][0]["payout_id"]
    _mod.release_payout_hold(tenant_id="demo", payout_id=pid)
    after = _mod.build_payout_delay_payload(tenant_id="demo", limit=5)
    row = next(p for p in after["payouts"] if p["payout_id"] == pid)
    assert row["status"] == "released"


def test_automation_disabled_no_new_holds() -> None:
    _mod._RELEASED_PAYOUT_IDS.clear()
    _mod.update_payout_delay_config(
        tenant_id="hold_off", automation_enabled=False, mule_score_hold_threshold=1
    )
    payload = _mod.build_payout_delay_payload(tenant_id="hold_off", limit=15)
    assert all(p["status"] == "pending" for p in payload["payouts"])
