"""Unit tests for DLQ envelope parsing (Prompt 171)."""

from __future__ import annotations

import json

from integration_ingress.nats_dead_letter_office import _parse_envelope


def test_parse_evaluate_4xx_envelope() -> None:
    payload = {
        "schema_version": "1",
        "kind": "evaluate_4xx",
        "status_code": 422,
        "nats_source_subject": "fraud.events.card_not_present",
        "event": {"tenant_id": "demo", "entity_id": "e1", "event_type": "card_not_present"},
    }
    row = _parse_envelope(json.dumps(payload).encode(), subject="fraud.events.dlq", sequence=99)
    assert row["kind"] == "evaluate_4xx"
    assert row["status_code"] == 422
    assert row["tenant_id"] == "demo"
    assert row["entity_id"] == "e1"
    assert row["event_type"] == "card_not_present"
    assert row["nats_source_subject"] == "fraud.events.card_not_present"


def test_parse_invalid_json() -> None:
    row = _parse_envelope(b"{not-json", subject="fraud.events.dlq", sequence=1)
    assert row["kind"] == "invalid_json"
    assert row["tenant_id"] is None
