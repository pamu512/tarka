"""Gate: ``tools/backtest_rules.py`` formats batch-replay scorecard output for operators."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


def _load_backtest_module():
    root = Path(__file__).resolve().parents[2]
    path = root / "tools" / "backtest_rules.py"
    spec = importlib.util.spec_from_file_location("backtest_rules", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod, root


def test_backtest_main_prints_block_allow_summary_table(capsys: pytest.CaptureFixture[str]) -> None:
    mod, root = _load_backtest_module()
    scorecard_path = root / "tools" / "fixtures" / "backtest_scorecard_gate.json"
    assert scorecard_path.is_file(), f"missing fixture: {scorecard_path}"

    rc = mod.main(
        [
            "--tenant",
            "gate-tenant",
            "--since",
            "2026-05-01T00:00:00Z",
            "--until",
            "2026-05-01T23:59:59Z",
            "--scorecard-input",
            str(scorecard_path),
        ],
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "batch-replay" in out
    assert "Predicted BLOCK" in out
    assert "Predicted ALLOW" in out
    assert "Actual BLOCK" in out
    assert "Actual ALLOW" in out
    assert "False positive rate" in out


def test_backtest_invokes_batch_replay_subprocess(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mod, root = _load_backtest_module()
    fixture = json.loads(
        (root / "tools" / "fixtures" / "backtest_scorecard_gate.json").read_text(encoding="utf-8"),
    )
    captured: list[list[str]] = []

    def _fake_run(cmd, **kwargs):
        captured.append(list(cmd))
        out_index = cmd.index("--scorecard-output") + 1
        Path(cmd[out_index]).write_text(json.dumps(fixture), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    rc = mod.main(
        [
            "--tenant",
            "gate-tenant",
            "--since",
            "2026-05-01T00:00:00Z",
            "--until",
            "2026-05-01T23:59:59Z",
            "--block-if-amount-gt",
            "5000",
            "--scorecard-output",
            str(tmp_path / "scorecard.json"),
        ],
    )
    assert rc == 0
    assert captured, "expected subprocess.run to be called"
    assert "batch-replay" in captured[0]
    assert "--rule-json" in captured[0]
    assert "--rule-content-id" in captured[0]
