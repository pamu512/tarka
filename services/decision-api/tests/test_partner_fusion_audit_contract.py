"""Wave 6: partner fusion maps to audit snapshot contract (evaluate→evidence)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from decision_api.partner_fusion import graph_writeback_hints, signals_to_feature_tags

_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "oss"
    / "fixtures"
    / "partner_fusion_signals.json"
)


def test_partner_evidence_audit_snapshot_shape():
    raw = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    sigs = [SimpleNamespace(**row) for row in raw["signals"]]
    feats, tags, evidence = signals_to_feature_tags(sigs)
    hints = graph_writeback_hints(
        tenant_id="t1",
        entity_id="e1",
        transaction_id="tx1",
        tags=tags,
        features=feats,
    )
    # Same keys pipeline.py writes onto payload_snapshot
    snap_extra = {
        "partner_evidence": evidence,
        "partner_graph_writeback": hints,
    }
    assert snap_extra["partner_evidence"]
    assert snap_extra["partner_graph_writeback"]["schema_id"] == (
        "tarka.partner_graph_writeback/v1"
    )
    assert any(e.get("vendor_id") == "fingerprint" for e in evidence)
    assert any(e.get("vendor_id") == "incognia" for e in evidence)
    assert "vendor:fingerprint" in tags
    assert feats.get("vendor_fingerprint_id")
    assert feats.get("vendor_incognia_place_id")
