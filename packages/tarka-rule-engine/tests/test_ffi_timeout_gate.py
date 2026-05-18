"""Gate: Rust FFI wall-clock deadline → fail-open response (graph signal dropped)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PKG_ROOT = Path(__file__).resolve().parents[1]
_PY_SRC = _PKG_ROOT / "python"
if str(_PY_SRC) not in sys.path:
    sys.path.insert(0, str(_PY_SRC))

pytest.importorskip("tarka_rule_engine._native")

import tarka_rule_engine._wrapper as wrapper  # noqa: E402
from tarka_rule_engine import RuleEngine  # noqa: E402


def test_rust_ffi_timeout_returns_fail_open_allow(monkeypatch: pytest.MonkeyPatch) -> None:
    class HangRust:
        def evaluate(self, graph_score: float, velocity_1h: int) -> dict[str, object]:
            import time

            time.sleep(30)
            return {"ok": True}

    monkeypatch.setattr(wrapper, "_RustRuleEngine", HangRust)
    monkeypatch.setenv("RULE_ENGINE_RUST_FFI_TIMEOUT_MS", "150")

    eng = RuleEngine()
    out = eng.evaluate(0.42, 9)
    assert out.get("ffi_timed_out") is True
    assert out.get("decision") == "ALLOW"
    assert out.get("graph_score") == 0.0
    assert out.get("velocity_1h") == 9
