"""Gate (Prompt 198): hourly production vs shadow block overlay series."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import duckdb

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import simulator  # noqa: E402


def test_block_overlay_shows_shadow_wave_production_missed() -> None:
    con = duckdb.connect(":memory:")
    con.execute(
        """
        CREATE TABLE raw_signals (
            ingested_at TIMESTAMP,
            session_id VARCHAR,
            signal_json VARCHAR,
            nats_stream_seq BIGINT
        )
        """,
    )
    base = datetime.now().replace(microsecond=0) - timedelta(hours=2)
    canvas = "canvas_wave_198"
    rows = []
    for i in range(8):
        rows.append(
            (
                base + timedelta(minutes=i * 5),
                f"shadow-{i}",
                json.dumps(
                    {
                        "ch": canvas,
                        "sid": f"shadow-{i}",
                        "metadata": {"acc_id": f"a{i}"},
                    },
                ),
                i + 1,
            ),
        )
    rows.append(
        (
            base + timedelta(minutes=40),
            "prod-1",
            json.dumps(
                {
                    "ch": "other",
                    "sid": "prod-1",
                    "metadata": {"production_decision": "deny", "acc_id": "p1"},
                },
            ),
            99,
        ),
    )
    con.executemany("INSERT INTO raw_signals VALUES (?, ?, ?, ?)", rows)

    rule = {"id": "r198", "when": [{"op": "eq", "field": "canvas_hash", "value": canvas}]}
    series = simulator.build_block_overlay_timeseries(
        rule,
        duckdb_connection=con,
        lookback_days=7,
    )
    assert series
    total_shadow = sum(p["shadow_blocks"] for p in series)
    total_prod = sum(p["production_blocks"] for p in series)
    total_shadow_only = sum(p["shadow_only_blocks"] for p in series)
    assert total_shadow >= 8
    assert total_prod >= 1
    assert total_shadow_only >= 7
