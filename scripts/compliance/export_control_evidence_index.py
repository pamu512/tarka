#!/usr/bin/env python3
"""Emit a machine-readable index of control evidence docs (not a certification pack)."""

from __future__ import annotations

import json
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_PATHS = [
    "docs/compliance/CLAIM_LOCK.md",
    "docs/compliance/soc2-pci/01-fail-closed-database-architecture.md",
    "docs/STUB_REGISTER.md",
    "docs/TIER_1_HONESTY_PROGRAM.md",
    "docs/docs/guides/shadow-and-ab-testing.md",
    "docs/docs/guides/partner-enrichment-fusion.md",
    "docs/docs/guides/calibration-ops-runbook.md",
    "docs/docs/guides/feature-serving-contract.md",
    "docs/compliance/partner-fusion-proof.stable.sha256",
    "docs/compliance/partner-fusion-proof.live.status",
    "scripts/oss/partner_fusion_tenant_proof.py",
    "scripts/oss/partner_fusion_live_status_gate.py",
    "scripts/oss/loyalty_feed_posture_smoke.py",
    "scripts/audit_stubs.py",
]


def main() -> int:
    out_dir = _REPO / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    items = []
    missing = []
    for rel in _PATHS:
        ok = (_REPO / rel).is_file()
        items.append({"path": rel, "exists": ok})
        if not ok:
            missing.append(rel)
    payload = {
        "schema_id": "tarka.control_evidence_index/v1",
        "complete": not missing,
        "missing": missing,
        "items": items,
    }
    out = out_dir / "control-evidence-index.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(out)
    if missing:
        print("MISSING:", *missing, sep="\n  ", file=__import__("sys").stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
