"""event_time helpers (PYTHONPATH includes ../shared)."""

from event_time import (
    event_time_unix_for_evaluate,
    event_time_unix_from_payload_snapshot,
    parse_event_time_to_unix,
)


def test_parse_event_time_iso_z():
    t = parse_event_time_to_unix("2026-04-01T12:00:00Z")
    assert t is not None
    assert abs(t - 1775044800.0) < 1.0


def test_event_time_for_evaluate_metadata_wins():
    t = event_time_unix_for_evaluate(
        {"event_time": "2026-04-01T12:00:00Z"},
        {"event_time": "2020-01-01T00:00:00Z"},
    )
    assert t is not None
    assert abs(t - 1775044800.0) < 1.0


def test_event_time_from_payload_snapshot():
    t = event_time_unix_from_payload_snapshot(
        {
            "metadata": {"event_time": 1775044800.0},
            "payload": {},
        }
    )
    assert t == 1775044800.0
