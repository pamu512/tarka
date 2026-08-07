"""Unit tests for Tarka Command Center aggregate (Prompt 188)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_MOD_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "integration_ingress" / "command_center.py"
)
_spec = importlib.util.spec_from_file_location("command_center", _MOD_PATH)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["command_center"] = _mod
_spec.loader.exec_module(_mod)


@pytest.mark.asyncio
async def test_command_center_payload() -> None:
    payload = await _mod.build_command_center_payload(tenant_id="demo")
    assert payload["tenant_id"] == "demo"
    assert len(payload["hero_kpis"]) >= 4
    assert len(payload["modules"]) >= 10
    assert isinstance(payload["action_queue"], list)


@pytest.mark.asyncio
async def test_modules_include_new_features() -> None:
    payload = await _mod.build_command_center_payload(tenant_id="demo")
    ids = {m["id"] for m in payload["modules"]}
    assert "promo_abuse" in ids
    assert "review_rings" in ids
    assert "regional_risk" in ids
