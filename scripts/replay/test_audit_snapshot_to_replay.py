from __future__ import annotations

import json
from pathlib import Path

from scripts.replay.audit_snapshot_to_replay import (
    audit_row_to_replay_record,
    convert_audit_jsonl,
)

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "audit_payload_snapshot.jsonl"


def test_audit_row_prefers_event_time_in_snapshot():
    rec = audit_row_to_replay_record(
        trace_id="t1",
        tenant_id="parity_smoke",
        entity_id="entity_a",
        payload_snapshot={
            "payload": {"amount": 1.0},
            "metadata": {"event_time": 1700000200.0},
        },
        created_at="2023-11-14T22:16:40+00:00",
    )
    assert rec["event_id"] == "t1"
    assert rec["fields"]["amount"] == 1.0
    assert rec["ts"] == 1700000200.0


def test_convert_audit_fixture_to_replay_shape(tmp_path: Path):
    out = tmp_path / "replay.jsonl"
    n = convert_audit_jsonl(_FIXTURE, out)
    assert n == 3
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line]
    assert rows[0]["tenant_id"] == "parity_smoke"
    assert rows[0]["entity_id"] == "entity_a"
    assert rows[0]["fields"]["device_id"] == "d1"
    assert "payload_snapshot" not in rows[0]
    assert rows[1]["ts"] == 1700000200.0
