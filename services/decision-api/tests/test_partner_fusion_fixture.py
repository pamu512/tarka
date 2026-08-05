"""Wave 5: fixture-based partner fusion (no live vendor keys)."""

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


def test_partner_fusion_fixture_file_maps_to_graph_hints():
    assert _FIXTURE.is_file(), f"missing fixture {_FIXTURE}"
    raw = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    sigs = [SimpleNamespace(**row) for row in raw["signals"]]
    feats, tags, evidence = signals_to_feature_tags(sigs)
    assert feats.get("vendor_fingerprint_id") == "vis-fixture-1"
    assert feats.get("vendor_incognia_place_id") == "place-fixture-9"
    assert "vendor:fingerprint" in tags
    assert any(t.startswith("vendor:incognia") for t in tags)
    assert len(evidence) == 2
    hints = graph_writeback_hints(
        tenant_id="t-fixture",
        entity_id="e-fixture",
        transaction_id="tx-fixture",
        tags=tags,
        features=feats,
    )
    assert any(v.get("label") == "Device" for v in hints["vertices"])
    assert any(v.get("label") == "Place" for v in hints["vertices"])
    assert any(e.get("type") == "USED_DEVICE" for e in hints["edges"])
    assert any(e.get("type") == "SEEN_AT" for e in hints["edges"])
