"""Gate: ``tools/backtest_rules.py`` runs and prints Block vs Allow prediction counts."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest


def _load_backtest_module():
    root = Path(__file__).resolve().parents[2]
    path = root / "tools" / "backtest_rules.py"
    spec = importlib.util.spec_from_file_location("backtest_rules", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, root


def _install_fake_tarka() -> None:
    """Minimal stub so ``main()`` runs without the real PyO3 wheel in CI."""

    class _Dec:
        __slots__ = ("decision", "is_partial")

        def __init__(self, decision: bool, is_partial: bool = False) -> None:
            self.decision = decision
            self.is_partial = is_partial

    def _rule_content_id(rule_json: str) -> str:
        return hashlib.sha256(rule_json.encode("utf-8")).hexdigest()

    def _evaluate(rule_json: str, data_json: str, rule_hex: str, *, fast_path: bool = True, **_: object) -> _Dec:
        _ = rule_json, rule_hex, fast_path
        amt = float(json.loads(data_json)["amount"])
        return _Dec(amt > 5000.0)

    decision_mod = types.ModuleType("tarka.decision")
    decision_mod.rule_content_id = _rule_content_id
    decision_mod.evaluate = _evaluate
    pkg = types.ModuleType("tarka")
    pkg.decision = decision_mod
    sys.modules["tarka"] = pkg
    sys.modules["tarka.decision"] = decision_mod


@pytest.fixture(autouse=True)
def _cleanup_fake_tarka():
    yield
    sys.modules.pop("tarka", None)
    sys.modules.pop("tarka.decision", None)


def test_backtest_main_prints_block_allow_summary_table(capsys: pytest.CaptureFixture[str]) -> None:
    _install_fake_tarka()
    mod, root = _load_backtest_module()
    pq = (
        root
        / "tarka_v2_core"
        / "services"
        / "orchestrator"
        / "src"
        / "orchestrator"
        / "analytics"
        / "data"
        / "seed_data.parquet"
    )
    assert pq.is_file(), f"missing seed parquet: {pq}"
    rc = mod.main(
        [
            "--parquet",
            str(pq),
            "--limit",
            "2000",
            "--block-if-amount-gt",
            "5000",
            "--truth-split",
            "9000",
        ],
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Predicted BLOCK" in out
    assert "Predicted ALLOW" in out
    assert "Actual BLOCK" in out
    assert "Actual ALLOW" in out
    assert "False positive rate" in out
