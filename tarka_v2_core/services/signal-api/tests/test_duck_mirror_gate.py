"""
Gate: ``SELECT count(*) FROM raw_signals`` equals total validated payloads ingested
(equivalent to NATS message count).

The full worker waits ``SIGNAL_DUCK_MIRROR_FLUSH_SEC`` (default 5s) between disk commits; tests use a
short flush interval and **batched flushes** to represent sustained traffic without sleeping 60s.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import duckdb
import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
_REPO = Path(__file__).resolve().parents[4]
for _p in (_SRC, _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from signal_api.workers.duck_mirror import (  # noqa: E402
    ensure_raw_signals_table,
    flush_batch_to_duckdb,
    purge_expired_raw_signals,
    rows_from_validated,
)
from tarka_v2_core.schemas.ingestion import UnifiedSignalSchema  # noqa: E402


def _fake_msg(data: bytes, seq: int) -> MagicMock:
    m = MagicMock()
    m.data = data
    m.metadata.sequence.stream = seq
    return m


def _signal(session: str) -> UnifiedSignalSchema:
    return UnifiedSignalSchema.model_validate(
        {
            "ch": "d" * 64,
            "wv": "w",
            "dm": 4,
            "ip": "198.51.100.2",
            "px": False,
            "ua": "Mozilla/5.0 (duck-mirror-gate)",
            "sid": session,
            "ts": datetime.now(UTC).isoformat(),
            "sv": "92.0.0",
            "mv": 0.0,
            "tp": 0,
            "hh": False,
        },
    )


def test_row_count_matches_total_nats_equivalent_messages(tmp_path: Path) -> None:
    """
    Simulates **one minute** of traffic at **10 msg/s** (600 messages) via 6×100-message flushes,
    matching the invariant: ``count(*) == NATS message count``.
    """
    db = tmp_path / "transactions.duckdb"
    con = duckdb.connect(str(db))
    ensure_raw_signals_table(con)

    messages_per_second = 10
    duration_sec = 60
    total = messages_per_second * duration_sec
    chunk = 100
    assert total % chunk == 0

    written = 0
    for batch_idx in range(total // chunk):
        items: list[tuple[MagicMock, UnifiedSignalSchema]] = []
        for i in range(chunk):
            sid = str(uuid4())
            body = _signal(sid)
            raw = json.dumps(
                body.model_dump(mode="json", by_alias=True),
                separators=(",", ":"),
            ).encode()
            seq = batch_idx * chunk + i + 1
            items.append((_fake_msg(raw, seq), body))
        rows = rows_from_validated(items)
        written += flush_batch_to_duckdb(con, rows)

    assert written == total
    cnt = con.execute("SELECT count(*) FROM raw_signals").fetchone()[0]
    assert int(cnt) == total == 600
    con.close()


@pytest.mark.anyio
async def test_batch_flush_ack_smoke_with_stub_connection(tmp_path: Path) -> None:
    """Sanity: two flushes accumulate rows (mirrors two NATS batch windows)."""
    db = tmp_path / "t2.duckdb"
    con = duckdb.connect(str(db))
    ensure_raw_signals_table(con)

    b1 = _signal(str(uuid4()))
    m1 = _fake_msg(
        json.dumps(b1.model_dump(mode="json", by_alias=True), separators=(",", ":")).encode(),
        1,
    )
    flush_batch_to_duckdb(con, rows_from_validated([(m1, b1)]))
    b2 = _signal(str(uuid4()))
    m2 = _fake_msg(
        json.dumps(b2.model_dump(mode="json", by_alias=True), separators=(",", ":")).encode(),
        2,
    )
    flush_batch_to_duckdb(con, rows_from_validated([(m2, b2)]))

    assert con.execute("SELECT count(*) FROM raw_signals").fetchone()[0] == 2
    con.close()
    await asyncio.sleep(0)


def test_raw_signals_ttl_keeps_duckdb_size_stable_across_repeated_purges(tmp_path: Path) -> None:
    """
    Gate (Prompt 117): TTL purge removes rows past retention; repeated daily-style purges do not
    balloon the ``.duckdb`` file (simulates multi-day stability without wall-clock sleeps).
    """
    db = tmp_path / "ttl_mirror.duckdb"
    con = duckdb.connect(str(db))
    ensure_raw_signals_table(con)
    old_ts = "2019-06-01 12:00:00+00"
    payload = "{}"
    for i in range(900):
        con.execute(
            "INSERT INTO raw_signals (ingested_at, session_id, signal_json, nats_stream_seq) VALUES (?, ?, ?, ?)",
            [old_ts, f"old-{i}", payload, i],
        )
    con.execute(
        "INSERT INTO raw_signals (ingested_at, session_id, signal_json, nats_stream_seq) VALUES (now(), 'fresh', ?, NULL)",
        [payload],
    )
    con.close()

    def purge_round() -> tuple[int, int]:
        c = duckdb.connect(str(db))
        ensure_raw_signals_table(c)
        removed = purge_expired_raw_signals(c, ttl_days=30)
        c.close()
        return removed, db.stat().st_size

    size_before = db.stat().st_size
    removed_first, size_after_first = purge_round()
    assert removed_first == 900

    con2 = duckdb.connect(str(db))
    assert int(con2.execute("SELECT count(*) FROM raw_signals").fetchone()[0]) == 1
    con2.close()

    sizes = [size_before, size_after_first]
    for _ in range(6):
        n, sz = purge_round()
        assert n == 0
        sizes.append(sz)

    tail = sizes[1:]
    assert max(tail) - min(tail) < 512 * 1024, f"duckdb size drift too large across pseudo-days: {sizes}"
