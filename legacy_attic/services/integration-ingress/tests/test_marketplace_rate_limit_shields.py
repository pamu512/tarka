"""Unit tests for marketplace rate limit shields (Prompt 176)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MOD_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "integration_ingress" / "marketplace_rate_limit_shields.py"
)
_spec = importlib.util.spec_from_file_location("marketplace_rate_limit_shields", _MOD_PATH)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["marketplace_rate_limit_shields"] = _mod
_spec.loader.exec_module(_mod)


def test_normalize_shield_config_clamps() -> None:
    cfg = _mod.normalize_shield_config(requests_per_minute=5, burst=0)
    assert cfg["requests_per_minute"] == _mod.MIN_RPM
    assert cfg["burst"] == _mod.MIN_BURST


def test_evaluate_rate_limit_disabled_allows() -> None:
    _mod.reset_bucket("test-key-off")
    d = _mod.evaluate_rate_limit("test-key-off", enabled=False, rpm=10, burst=2, consume=True)
    assert d.allowed is True


def test_evaluate_rate_limit_throttles_when_exhausted() -> None:
    key = "test-key-throttle"
    _mod.reset_bucket(key)
    for _ in range(5):
        d = _mod.evaluate_rate_limit(key, enabled=True, rpm=60, burst=3, consume=True)
    assert d.allowed is False
    assert d.throttled is True
