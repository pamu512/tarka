"""Unit tests for DLQ envelope parsing (Prompt 171)."""

from __future__ import annotations

import json

from integration_ingress.nats_dead_letter_office import _dlq_config, _parse_envelope


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


def test_dlq_stream_ignores_global_events_stream_name(
    monkeypatch,
) -> None:
    """A2: a globally-set NATS_STREAM_NAME (live events) must never bind the DLQ office."""
    monkeypatch.setenv("NATS_STREAM_NAME", "FRAUD_EVENTS")
    monkeypatch.delenv("INGEST_DLQ_STREAM_NAME", raising=False)
    monkeypatch.delenv("NATS_DLQ_STREAM_NAME", raising=False)
    monkeypatch.delenv("INGEST_STREAM_NAME", raising=False)
    _, stream, _ = _dlq_config()
    assert stream == "FRAUD_DLQ", "DLQ office must not peek the live events stream"


def test_dlq_stream_dlq_specific_env_wins(monkeypatch) -> None:
    """A2: INGEST_DLQ_STREAM_NAME beats a globally-set NATS_STREAM_NAME."""
    monkeypatch.setenv("NATS_STREAM_NAME", "FRAUD_EVENTS")
    monkeypatch.setenv("INGEST_DLQ_STREAM_NAME", "FRAUD_DLQ")
    _, stream, _ = _dlq_config()
    assert stream == "FRAUD_DLQ"


def test_dlq_stream_nats_dlq_alias_respected(monkeypatch) -> None:
    monkeypatch.setenv("NATS_DLQ_STREAM_NAME", "CUSTOM_DLQ")
    monkeypatch.delenv("INGEST_DLQ_STREAM_NAME", raising=False)
    monkeypatch.delenv("NATS_STREAM_NAME", raising=False)
    _, stream, _ = _dlq_config()
    assert stream == "CUSTOM_DLQ"


def test_dlq_config_defaults(monkeypatch) -> None:
    for var in (
        "NATS_STREAM_NAME",
        "INGEST_DLQ_STREAM_NAME",
        "NATS_DLQ_STREAM_NAME",
        "INGEST_STREAM_NAME",
        "INGEST_DLQ_SUBJECT",
        "NATS_DLQ_SUBJECT",
        "INGEST_SUBJECT_PREFIX",
    ):
        monkeypatch.delenv(var, raising=False)
    subject, stream, prefix = _dlq_config()
    assert subject == "fraud.dlq.evaluate"
    assert stream == "FRAUD_DLQ"
    assert prefix == "fraud.events"
