from __future__ import annotations

import json
from pathlib import Path

from scripts.replay import replay_aggregates


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    lines = [json.dumps(r, separators=(",", ":")) for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_iter_rows_within_time_range(tmp_path: Path):
    f = tmp_path / "audit.jsonl"
    _write_jsonl(
        f,
        [
            {
                "tenant_id": "t1",
                "entity_id": "e1",
                "event_id": "e1",
                "fields": {"x": 1},
                "ts": 1000,
            },
            {
                "tenant_id": "t1",
                "entity_id": "e1",
                "event_id": "e2",
                "fields": {"x": 2},
                "ts": 2000,
            },
            {
                "tenant_id": "t1",
                "entity_id": "e1",
                "event_id": "e3",
                "fields": {"x": 3},
                "ts": 3000,
            },
        ],
    )
    rows = [
        r
        for r in replay_aggregates.iter_audit_rows(f)
        if (ts := replay_aggregates.row_timestamp_seconds(r)) is not None and 1500 <= ts <= 2500
    ]
    assert len(rows) == 1
    assert rows[0]["event_id"] == "e2"


def test_iter_rows_accepts_iso_window(tmp_path: Path):
    f = tmp_path / "audit_iso.jsonl"
    _write_jsonl(
        f,
        [
            {
                "tenant_id": "t1",
                "entity_id": "e1",
                "event_id": "a",
                "fields": {},
                "created_at": "2026-01-01T00:00:00+00:00",
            },
            {
                "tenant_id": "t1",
                "entity_id": "e1",
                "event_id": "b",
                "fields": {},
                "created_at": "2026-01-02T00:00:00+00:00",
            },
        ],
    )
    start = replay_aggregates.parse_time_bound("2026-01-01T12:00:00+00:00")
    end = replay_aggregates.parse_time_bound("2026-01-03T00:00:00+00:00")
    rows = [
        r
        for r in replay_aggregates.iter_audit_rows(f)
        if (ts := replay_aggregates.row_timestamp_seconds(r)) is not None and start <= ts <= end
    ]
    assert [r["event_id"] for r in rows] == ["b"]
