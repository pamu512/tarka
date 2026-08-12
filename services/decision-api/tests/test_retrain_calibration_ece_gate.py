"""ECE-gated calibration retrain — bad ECE blocks write; force overrides."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO / "scripts" / "oss" / "retrain_calibration_ece_gate.py"


def _load_mod():
    spec = importlib.util.spec_from_file_location(
        "retrain_calibration_ece_gate", _SCRIPT
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_labels(path: Path, rows: list[dict]) -> None:
    path.write_text(
        json.dumps({"schema_id": "tarka.calibration_retrain_labels/v1", "rows": rows}),
        encoding="utf-8",
    )


def _calibrated_rows(*, start_day: int, count: int, invert: bool = False) -> list[dict]:
    rows: list[dict] = []
    for i in range(count):
        label = i % 2
        score = 0.92 if label == 1 else 0.08
        if invert:
            score = 1.0 - score
        day = start_day + (i // 24)
        hour = i % 24
        rows.append(
            {
                "created_at": f"2026-01-{day:02d}T{hour:02d}:00:00+00:00",
                "integrity_confidence": score,
                "y_label": str(label),
                "trace_id": f"t-{start_day}-{i}",
            }
        )
    return rows


def test_bad_ece_does_not_write_candidate(tmp_path):
    labels = tmp_path / "labels.json"
    candidate = tmp_path / "candidate.json"
    candidate.write_text('{"prior": true}\n', encoding="utf-8")
    artifact = tmp_path / "artifact.json"
    train_rows = _calibrated_rows(start_day=1, count=20, invert=False)
    report_rows = _calibrated_rows(start_day=25, count=20, invert=True)
    _write_labels(labels, train_rows + report_rows)

    proc = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--labels",
            str(labels),
            "--out",
            str(candidate),
            "--artifact-out",
            str(artifact),
            "--train-fraction",
            "0.5",
            "--ece-threshold",
            "0.05",
        ],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, proc.stderr + proc.stdout
    assert candidate.read_text(encoding="utf-8") == '{"prior": true}\n'
    report = json.loads(artifact.read_text(encoding="utf-8"))
    assert report["gate_passed"] is False
    assert report["candidate_written"] is False
    assert report["ece"] > 0.05


def test_committed_fixture_passes_ece_gate(tmp_path):
    """Track A: CI fixture must pass chronological ECE gate (not production L3)."""
    fixture = (
        _REPO / "scripts" / "replay" / "fixtures" / "calibration_retrain_labels.json"
    )
    assert fixture.is_file()
    candidate = tmp_path / "candidate.json"
    artifact = tmp_path / "artifact.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--labels",
            str(fixture),
            "--out",
            str(candidate),
            "--artifact-out",
            str(artifact),
            "--train-fraction",
            "0.7",
            "--ece-threshold",
            "0.05",
        ],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": str(_REPO / "services" / "decision-api" / "src"),
        },
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    report = json.loads(artifact.read_text(encoding="utf-8"))
    assert report["gate_passed"] is True
    assert report["candidate_written"] is True
    assert report["report_rows"] >= 1
    cand = json.loads(candidate.read_text(encoding="utf-8"))
    assert cand["schema_id"] == "tarka.platt_calibration/v1"


def test_good_ece_writes_candidate(tmp_path):
    labels = tmp_path / "labels.json"
    candidate = tmp_path / "candidate.json"
    artifact = tmp_path / "artifact.json"
    rows = _calibrated_rows(start_day=1, count=120, invert=False)
    _write_labels(labels, rows)

    proc = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--labels",
            str(labels),
            "--out",
            str(candidate),
            "--artifact-out",
            str(artifact),
            "--train-fraction",
            "0.7",
        ],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert candidate.is_file()
    cand = json.loads(candidate.read_text(encoding="utf-8"))
    assert cand["schema_id"] == "tarka.platt_calibration/v1"
    assert "A" in cand and "B" in cand
    report = json.loads(artifact.read_text(encoding="utf-8"))
    assert report["gate_passed"] is True
    assert report["candidate_written"] is True
    assert report["force"] is False
    assert report["ece"] <= 0.05


def test_force_writes_despite_bad_ece(tmp_path):
    labels = tmp_path / "labels.json"
    candidate = tmp_path / "candidate.json"
    artifact = tmp_path / "artifact.json"
    train_rows = _calibrated_rows(start_day=1, count=20, invert=False)
    report_rows = _calibrated_rows(start_day=25, count=20, invert=True)
    _write_labels(labels, train_rows + report_rows)

    proc = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--labels",
            str(labels),
            "--out",
            str(candidate),
            "--artifact-out",
            str(artifact),
            "--train-fraction",
            "0.5",
            "--force",
        ],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert candidate.is_file()
    report = json.loads(artifact.read_text(encoding="utf-8"))
    assert report["force"] is True
    assert report["candidate_written"] is True
    assert report["gate_passed"] is False


def test_fit_only_on_train_window(tmp_path):
    mod = _load_mod()
    rows = _calibrated_rows(start_day=1, count=40, invert=False)
    result = mod.retrain(
        [
            {
                "created_at": r["created_at"],
                "score": r["integrity_confidence"],
                "y_label": int(r["y_label"]),
            }
            for r in rows
        ],
        train_fraction=0.5,
        train_end=None,
        ece_threshold=0.05,
        force=False,
    )
    assert result["train_rows"] == 20
    assert result["report_rows"] == 20


def test_train_end_split(tmp_path):
    mod = _load_mod()
    rows = _calibrated_rows(start_day=1, count=40, invert=False)
    parsed = [
        {
            "created_at": r["created_at"],
            "score": r["integrity_confidence"],
            "y_label": int(r["y_label"]),
        }
        for r in rows
    ]
    result = mod.retrain(
        parsed,
        train_end="2026-01-01T12:00:00+00:00",
        train_fraction=None,
        ece_threshold=0.05,
        force=False,
    )
    assert result["split_meta"]["split"] == "train_end"
    assert result["train_rows"] == 13
    assert result["report_rows"] == 27


def test_platt_and_ece_helpers():
    mod = _load_mod()
    scores = [0.05, 0.08, 0.92, 0.95] * 25
    labels = [0, 0, 1, 1] * 25
    a, b = mod.fit_platt(scores, labels)
    probs = [mod.apply_platt(s, a, b) for s in scores]
    assert mod.brier_score(probs, labels) < 0.05
    assert mod.expected_calibration_error(probs, labels) < 0.05
