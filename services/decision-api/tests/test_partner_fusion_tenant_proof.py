"""Tenant proof script — fixture mode must emit SHA + case evidence."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO / "scripts" / "oss" / "partner_fusion_tenant_proof.py"


def _load_proof_module():
    spec = importlib.util.spec_from_file_location("partner_fusion_tenant_proof", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


def test_require_live_fails_without_partner_evidence(tmp_path, monkeypatch):
    monkeypatch.delenv("DECISION_API_URL", raising=False)
    monkeypatch.setenv("REQUIRE_LIVE_PARTNER_PROOF", "1")
    out = tmp_path / "proof.json"
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--mode", "fixture", "--out", str(out)],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "REQUIRE_LIVE_PARTNER_PROOF" in proc.stderr
    assert not out.is_file()


def test_require_live_fails_when_live_has_no_evidence(monkeypatch, tmp_path):
    mod = _load_proof_module()
    monkeypatch.setenv("REQUIRE_LIVE_PARTNER_PROOF", "1")
    monkeypatch.setenv("DECISION_API_URL", "http://decision.test")
    monkeypatch.setenv("FINGERPRINT_REQUEST_ID", "req-test")

    def _empty_live(_tenant_id: str) -> dict:
        return {
            "schema_id": "tarka.partner_fusion_proof/v1",
            "generated_at": "2026-08-05T00:00:00+00:00",
            "mode": "live",
            "tenant_id": "proof-tenant",
            "trace_id": "trace-empty",
            "audit_snapshot": {"partner_evidence": [], "partner_graph_writeback": {}},
            "case_evidence": {},
            "ok": False,
            "content_sha256": "deadbeef",
        }

    monkeypatch.setattr(mod, "_live_proof", _empty_live)
    out = tmp_path / "proof.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [str(_SCRIPT), "--mode", "live", "--out", str(out)],
    )
    assert mod.main() == 1
    proof = json.loads(out.read_text(encoding="utf-8"))
    assert proof["mode"] == "live"
    assert not proof["audit_snapshot"]["partner_evidence"]
