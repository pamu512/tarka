"""Contract v1 event mapping for graph hints and outbox payloads."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC_ORCH = Path(__file__).resolve().parents[1]
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
_SRC_SHARED = Path(__file__).resolve().parents[2] / "shared"
for _p in (_SRC_ORCH, _SRC_INGESTOR, _SRC_SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_graph_hints_from_event_reads_payload_and_metadata() -> None:
    from graph.client import graph_hints_from_event

    hints = graph_hints_from_event(
        {
            "tenant_id": "acme",
            "entity_id": "user-9",
            "event_type": "login",
            "payload": {"device_id": "d1", "ip": "1.1.1.1"},
            "metadata": {"email": "a@b.co"},
        },
    )
    assert hints.device_id == "d1"
    assert hints.ip == "1.1.1.1"
    assert hints.email == "a@b.co"
    assert hints.user_id == "user-9"


def test_graph_payload_prefers_event_over_envelope() -> None:
    from workers.handlers.graph_ingest import _event_from_graph_payload

    ev = _event_from_graph_payload(
        {
            "event": {
                "tenant_id": "t",
                "entity_id": "e1",
                "event_type": "payment",
                "payload": {"amount": 1},
            },
            "edge_transaction_payload_envelope": {
                "entity_id": "00000000-0000-0000-0000-000000000001",
                "amount": 9,
                "timestamp": "2026-01-01T00:00:00Z",
                "metadata": {"tenant_id": "other"},
            },
        },
    )
    assert ev["entity_id"] == "e1"
    assert ev["tenant_id"] == "t"
