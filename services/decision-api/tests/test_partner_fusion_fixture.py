"""Wave 5: fixture-based partner fusion (no live vendor keys)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from decision_api.partner_fusion import (
    graph_writeback_hints,
    graph_writes_from_hints,
    signals_to_feature_tags,
)

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
    entities, links = graph_writes_from_hints(hints)
    assert any(
        e["entity_type"] == "Device" and e["external_id"].startswith("fp:")
        for e in entities
    )
    assert any(e["entity_type"] == "Place" for e in entities)
    assert not any(e["entity_type"] == "Entity" for e in entities)
    assert any(
        lk["relationship"] == "USED_DEVICE" and lk["from_external_id"] == "e-fixture"
        for lk in links
    )


def test_opensanctions_match_writes_list_hop():
    from types import SimpleNamespace

    sigs = [
        SimpleNamespace(
            vendor_id="opensanctions",
            score_0_100=92.0,
            reason_codes=["opensanctions:match", "opensanctions:high_confidence"],
            raw_meta={"top_id": "NK-1", "match_count": 1},
        )
    ]
    feats, tags, _ = signals_to_feature_tags(sigs)
    assert feats.get("vendor_opensanctions_list_id") == "NK-1"
    assert "vendor:opensanctions" in tags
    hints = graph_writeback_hints(
        tenant_id="t-list",
        entity_id="alice",
        transaction_id="tx-list",
        tags=tags,
        features=feats,
    )
    assert any(
        v.get("label") == "List" and v.get("id") == "list:NK-1"
        for v in hints["vertices"]
    )
    assert any(e.get("type") == "HAS_LIST" for e in hints["edges"])
    entities, links = graph_writes_from_hints(hints)
    assert any(
        e["entity_type"] == "List" and e["external_id"] == "list:NK-1" for e in entities
    )
    assert any(
        lk["relationship"] == "HAS_LIST" and lk["from_external_id"] == "alice"
        for lk in links
    )


def test_opensanctions_no_match_does_not_write_list():
    from types import SimpleNamespace

    sigs = [
        SimpleNamespace(
            vendor_id="opensanctions",
            score_0_100=5.0,
            reason_codes=["opensanctions:no_match"],
            raw_meta={"match_count": 0},
        )
    ]
    feats, tags, _ = signals_to_feature_tags(sigs)
    assert not feats.get("vendor_opensanctions_list_id")
    hints = graph_writeback_hints(
        tenant_id="t-list",
        entity_id="alice",
        transaction_id="tx-list",
        tags=tags,
        features=feats,
    )
    assert not any(v.get("label") == "List" for v in hints["vertices"])
    assert not any(e.get("type") == "HAS_LIST" for e in hints["edges"])
