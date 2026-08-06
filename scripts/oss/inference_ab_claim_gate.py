#!/usr/bin/env python3
"""Inference A+B claim gate — both Track A (ECE) and Track B (S9) must pass.

Writes artifacts/inference_ab_claim.json. Exit 1 if either track fails.
Fixture bar only — not live warehouse L3 / named-tenant labels.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCHEMA = "tarka.inference_ab_claim/v1"


def _run(cmd: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(_REPO),
        capture_output=True,
        text=True,
        env=env,
    )


def main() -> int:
    art_dir = Path(
        os.environ.get("INFERENCE_AB_ARTIFACT_DIR", str(_REPO / "artifacts"))
    )
    art_dir.mkdir(parents=True, exist_ok=True)

    ece_labels = _REPO / "scripts" / "replay" / "fixtures" / "calibration_retrain_labels.json"
    ece_candidate = art_dir / "platt_candidate.json"
    ece_report = art_dir / "calibration_retrain_report.json"
    loyalty_report = art_dir / "loyalty_economics_feed_smoke.json"

    env_a = {
        **os.environ,
        "PYTHONPATH": str(_REPO / "services" / "decision-api" / "src"),
    }
    proc_a = _run(
        [
            sys.executable,
            str(_REPO / "scripts" / "oss" / "retrain_calibration_ece_gate.py"),
            "--labels",
            str(ece_labels),
            "--out",
            str(ece_candidate),
            "--artifact-out",
            str(ece_report),
            "--train-fraction",
            "0.7",
            "--ece-threshold",
            "0.05",
        ],
        env=env_a,
    )
    track_a_ok = proc_a.returncode == 0
    ece_body: dict = {}
    if ece_report.is_file():
        ece_body = json.loads(ece_report.read_text(encoding="utf-8"))
        track_a_ok = track_a_ok and ece_body.get("gate_passed") is True

    env_b = {
        **os.environ,
        "LOYALTY_ECONOMICS_ARTIFACT": str(loyalty_report),
    }
    proc_b = _run(
        [sys.executable, str(_REPO / "scripts" / "oss" / "loyalty_economics_feed_smoke.py")],
        env=env_b,
    )
    track_b_ok = proc_b.returncode == 0
    loyalty_body: dict = {}
    if loyalty_report.is_file():
        loyalty_body = json.loads(loyalty_report.read_text(encoding="utf-8"))
        track_b_ok = track_b_ok and loyalty_body.get("ok") is True

    claim_ok = track_a_ok and track_b_ok
    out = {
        "schema_id": _SCHEMA,
        "ok": claim_ok,
        "inference_score_claim": 4.5 if claim_ok else None,
        "bar": "fixture_ci",
        "disclaimer": (
            "Fixture chronological labels + S9 feed pack — not live warehouse L3 "
            "or named-tenant production loyalty effectiveness."
        ),
        "track_a": {
            "ok": track_a_ok,
            "gate_passed": ece_body.get("gate_passed"),
            "ece": ece_body.get("ece"),
            "stderr": (proc_a.stderr or "")[-500:],
        },
        "track_b": {
            "ok": track_b_ok,
            "cases_ok": loyalty_body.get("ok"),
            "stderr": (proc_b.stderr or "")[-500:],
        },
    }
    claim_path = art_dir / "inference_ab_claim.json"
    claim_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0 if claim_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
