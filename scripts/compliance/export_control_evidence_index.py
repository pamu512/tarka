#!/usr/bin/env python3
"""Emit a machine-readable index of customer control evidence docs (maturity Wave 4 + Risk 4.2)."""

from __future__ import annotations

import json
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_PATHS = [
    "docs/compliance/customer-control-evidence-pack.md",
    "docs/compliance/soc2-pci/01-fail-closed-database-architecture.md",
    "docs/STUB_REGISTER.md",
    "docs/TIER_1_HONESTY_PROGRAM.md",
    "docs/docs/operations/slo-burn-response.md",
    "docs/docs/guides/shadow-and-ab-testing.md",
    "docs/docs/guides/partner-enrichment-fusion.md",
    "docs/docs/guides/calibration-ops-runbook.md",
    "docs/compliance/partner-fusion-proof-runbook.md",
    "docs/compliance/partner-fusion-proof.stable.sha256",
    "docs/compliance/partner-fusion-proof.live.status",
    "docs/compliance/partner-fusion-proof.live.attempt.md",
    "docs/compliance/CLAIM_LOCK.md",
    "docs/superpowers/playbooks/l3-ops-ledger.md",
    "scripts/oss/partner_fusion_tenant_proof.py",
    "scripts/oss/partner_fusion_live_status_gate.py",
    "services/decision-api/tests/test_kill_criteria_promote_gate.py",
    "scripts/audit_stubs.py",
]


def main() -> int:
    out_dir = _REPO / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    items = []
    for rel in _PATHS:
        p = _REPO / rel
        items.append({"path": rel, "exists": p.is_file()})
    payload = {
        "schema_id": "tarka.control_evidence_index/v1",
        "items": items,
        "missing": [i["path"] for i in items if not i["exists"]],
    }
    dest = out_dir / "control-evidence-index.json"
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(dest)
    if payload["missing"]:
        print("export_control_evidence_index: FAIL missing:", file=__import__("sys").stderr)
        for m in payload["missing"]:
            print(f"  - {m}", file=__import__("sys").stderr)
        return 1
    print("export_control_evidence_index: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
