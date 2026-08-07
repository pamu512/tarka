"""Smoke: four-week shadow sim writes non-claiming artifact with metric keys."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO / "scripts" / "oss" / "shadow_four_week_sim.py"
_REQUIRED_KEYS = ("banner", "precision", "recall", "insult_proxy")


def test_shadow_four_week_sim_smoke(tmp_path):
    out = tmp_path / "shadow_four_week_sim.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--seed",
            "42",
            "--out",
            str(out),
        ],
        cwd=str(_REPO),
        env={**__import__("os").environ, "PYTHONPATH": "services/decision-api/src:."},
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    artifact = json.loads(out.read_text(encoding="utf-8"))
    for key in _REQUIRED_KEYS:
        assert key in artifact, f"missing key: {key}"
    assert artifact["banner"] == "NOT PRODUCTION L3"
    assert isinstance(artifact["precision"], (int, float))
    assert isinstance(artifact["recall"], (int, float))
    assert isinstance(artifact["insult_proxy"], (int, float))
    assert len(artifact.get("weeks") or []) == 4
