"""Tenant proof script — fixture mode must emit SHA + case evidence."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO / "scripts" / "oss" / "partner_fusion_tenant_proof.py"


def test_fixture_partner_fusion_tenant_proof(tmp_path):
    out = tmp_path / "proof.json"
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--mode", "fixture", "--out", str(out)],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    proof = json.loads(out.read_text(encoding="utf-8"))
    assert proof["ok"] is True
    assert proof["mode"] == "fixture"
    assert proof["audit_snapshot"]["partner_evidence"]
    assert proof["case_evidence"]["decision_audit"]["payload_snapshot"][
        "partner_evidence"
    ]
    assert proof.get("stable_sha256")
    assert (tmp_path / "proof.sha256").is_file()
