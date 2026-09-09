"""G2.3 — named edges on the evaluate receipt. Empty URL = hops off."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from graph_contract import UnsignedGraphToken, require_etype
from graph_pack_atoms import (
    hop_view_from_graph_meta,
    pack_why_from_hop,
    require_pack_etype,
)

from decision_api.graph_hop_contract import graph_pack_why
from decision_api.receipt_export import receipt_row_from_audit

_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "graphs"
    / "graph-named-edge-uses-device.json"
)
_RULES = Path(__file__).resolve().parents[1] / "rules"
_CLAIM = Path(__file__).resolve().parents[3] / "docs" / "compliance" / "CLAIM_LOCK.md"
_PLANES = (
    Path(__file__).resolve().parents[3] / "docs" / "contracts" / "graph-planes-v1.md"
)


def _audit(snap: dict) -> SimpleNamespace:
    return SimpleNamespace(
        trace_id=uuid4(),
        tenant_id="t1",
        entity_id="alice",
        event_type="login",
        decision="allow",
        score=1.0,
        payload_snapshot=snap,
        created_at=datetime(2026, 9, 9, tzinfo=timezone.utc),
    )


def test_empty_url_receipt_is_graph_missing_no_invented_neighbors() -> None:
    leaked = {
        "named_edges": [
            {"from_id": "alice", "to_id": "ghost-sib", "type": "USES_DEVICE"}
        ],
        "multi_id_user_ids": ["ghost-sib"],
        "parties": [{"entity_id": "invented-neighbor", "role": "member"}],
    }
    why = graph_pack_why(leaked, graph_url="", tenant_id="t1", subject_id="alice")
    hop = hop_view_from_graph_meta(
        leaked, graph_url="", tenant_id="t1", subject_id="alice"
    )
    assert why["graph"]["status"] == "graph:missing"
    assert why["graph"]["named_edges"] == []
    assert why["graph"]["multi_id_user_ids"] == []
    assert why["graph"]["invented_edges"] is False
    assert hop["named_edges"] == []
    assert hop["multi_id_user_ids"] == []

    row = receipt_row_from_audit(
        _audit(
            {
                "graph_hop_v1": hop,
                "pack_why": why,
            }
        )
    )
    assert row["hop_summary"] == "graph:missing"
    assert row["named_edges"] == []
    assert row["invented_edges"] is False
    blob = json.dumps(row)
    assert "ghost-sib" not in blob
    assert "invented-neighbor" not in blob
    assert "parties" not in row


def test_url_set_fixture_named_edges_on_receipt() -> None:
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    hop = hop_view_from_graph_meta(
        fixture, graph_url="http://graph.test", tenant_id="t1", subject_id="alice"
    )
    why = pack_why_from_hop(hop)
    assert hop["status"] == "graph:ok"
    assert why["named_edges"] == [
        {"from_id": "alice", "to_id": "dev-1", "type": "USES_DEVICE"}
    ]
    row = receipt_row_from_audit(
        _audit({"graph_hop_v1": hop, "pack_why": {"graph": why}})
    )
    assert row["hop_summary"] == "graph:ok"
    assert row["named_edges"] == [
        {"from_id": "alice", "to_id": "dev-1", "type": "USES_DEVICE"}
    ]
    assert row["named_edges"][0]["type"] == "USES_DEVICE"
    assert row["named_edges"][0]["from_id"] == "alice"
    assert row["named_edges"][0]["to_id"] == "dev-1"
    assert row["invented_edges"] is False


def test_unsigned_etype_still_refused() -> None:
    with pytest.raises(UnsignedGraphToken, match="etype"):
        require_etype("t1", "RELATED")
    with pytest.raises(UnsignedGraphToken, match="etype"):
        require_pack_etype("t1", "GHOST_EDGE")
    hop = hop_view_from_graph_meta(
        {"named_edges": [{"from_id": "a", "to_id": "b", "type": "RELATED"}]},
        graph_url="http://graph.test",
        tenant_id="t1",
        subject_id="a",
    )
    why = pack_why_from_hop(hop)
    assert why["named_edges"][0]["type"] == "RELATED"
    assert why["named_edges"][0]["type"] != "USES_DEVICE"
    row = receipt_row_from_audit(
        _audit({"graph_hop_v1": hop, "pack_why": {"graph": why}})
    )
    assert row["named_edges"][0]["type"] == "RELATED"


def test_parties_only_when_provided_not_invented_from_hops() -> None:
    hop = hop_view_from_graph_meta(
        {
            "named_edges": [
                {"from_id": "alice", "to_id": "dev-1", "type": "USES_DEVICE"}
            ]
        },
        graph_url="http://graph.test",
        tenant_id="t1",
        subject_id="alice",
    )
    why = pack_why_from_hop(hop)
    assert "parties" not in why
    row = receipt_row_from_audit(
        _audit({"graph_hop_v1": hop, "pack_why": {"graph": why}})
    )
    assert "parties" not in row
    assert all(
        (e.get("to_id") != "alice" or e.get("from_id") == "alice")
        for e in row["named_edges"]
    )

    provided = [{"entity_id": "bob", "role": "member"}]
    row_with = receipt_row_from_audit(
        _audit(
            {
                "graph_hop_v1": hop,
                "pack_why": {"graph": why},
                "parties": provided,
            }
        )
    )
    assert row_with["parties"] == provided
    assert [p["entity_id"] for p in row_with["parties"]] == ["bob"]
    assert "dev-1" not in {p.get("entity_id") for p in row_with["parties"]}


def test_hop_packs_stay_shadow_and_claim_lock_hop_rows() -> None:
    for name in (
        "graph_v1_uses_device_v1.json",
        "graph_v1_has_instrument_v1.json",
        "graph_v1_has_list_v1.json",
    ):
        pack = json.loads((_RULES / name).read_text(encoding="utf-8"))
        assert pack.get("mode") == "shadow"

    lock = _CLAIM.read_text(encoding="utf-8")
    planes = _PLANES.read_text(encoding="utf-8")
    assert "Empty `GRAPH_SERVICE_URL` ≠ sibling identity (`graph:missing`" in lock
    assert "named_edges []" in lock
    assert "Closed omniscient AI author loop" in lock
    assert "invented neighbors" in lock
    assert "Hop packs `mode=shadow`" in lock
    assert "Always-on graph" in lock
    assert "named edges" in planes.lower()
    assert "type" in planes.lower() and "endpoint" in planes.lower()
    assert "graph:missing" in planes
    assert "mode=shadow" in planes
    assert "parties[]" in planes
    assert "identity sku" not in planes.lower()
