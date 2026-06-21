"""Unit tests for mule path visualizer (Prompt 179)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MOD_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "integration_ingress" / "mule_path_visualizer.py"
)
_spec = importlib.util.spec_from_file_location("mule_path_visualizer", _MOD_PATH)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["mule_path_visualizer"] = _mod
_spec.loader.exec_module(_mod)


def test_build_mule_path_three_hops() -> None:
    payload = _mod.build_mule_path_payload(tenant_id="demo")
    assert len(payload["hops"]) == 3
    assert payload["hops"][0]["role"] == "origin"
    assert payload["hops"][1]["role"] == "mule"
    assert payload["hops"][2]["role"] == "payout"
    assert len(payload["transfers"]) == 2


def test_fraud_frank_template() -> None:
    payload = _mod.build_mule_path_payload(
        tenant_id="demo",
        origin_entity_id="fraud_frank",
        mule_entity_id="mule_jane",
    )
    assert payload["hops"][0]["entity_id"] == "fraud_frank"
    assert payload["hops"][1]["entity_id"] == "mule_jane"
