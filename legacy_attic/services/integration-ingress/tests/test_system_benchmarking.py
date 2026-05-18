"""Unit tests for system benchmarking helpers (Prompt 178)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "src" / "integration_ingress" / "system_benchmarking.py"
_spec = importlib.util.spec_from_file_location("system_benchmarking", _MOD_PATH)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["system_benchmarking"] = _mod
_spec.loader.exec_module(_mod)


def test_classify_vs_target() -> None:
    assert _mod.classify_vs_target(0.8) == "on_target"
    assert _mod.classify_vs_target(1.5) == "near_target"
    assert _mod.classify_vs_target(3.0) == "over_target"
    assert _mod.classify_vs_target(None) == "unavailable"


def test_percentile_and_bench_row() -> None:
    row = _mod._bench_row(
        probe_id="t",
        label="Test",
        plane="host",
        samples=[0.5, 0.8, 1.2, 0.9, 1.0, 0.7, 2.5],
    )
    assert row["p95_ms"] is not None
    assert row["status"] in ("on_target", "near_target", "over_target")
