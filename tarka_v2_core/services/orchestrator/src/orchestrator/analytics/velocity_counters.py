"""ClickHouse mirror for Anumana fixed-window velocity counters (``anumana:velocity:*``)."""

from __future__ import annotations

import logging
import threading
from typing import Any

from orchestrator.anumana_velocity import TransactionVelocityCommand

logger = logging.getLogger(__name__)

_VELOCITY_COUNTERS_TABLE = "orchestrator_velocity_counters"
_DDL = f"""
CREATE TABLE IF NOT EXISTS {_VELOCITY_COUNTERS_TABLE} (
    redis_key String,
    increment Int64
) ENGINE = SummingMergeTree
ORDER BY (redis_key)
"""


def ensure_velocity_counters_table(client: Any) -> None:
    client.command(_DDL)


def apply_velocity_counter_increments(
    client: Any,
    commands: list[TransactionVelocityCommand],
    *,
    lock: threading.Lock | None = None,
) -> None:
    """Insert SummingMergeTree rows that mirror Redis ``INCRBY`` deltas."""
    if not commands:
        return
    rows = [[cmd.redis_key, int(cmd.increment)] for cmd in commands]
    if lock is None:
        client.insert(
            _VELOCITY_COUNTERS_TABLE,
            rows,
            column_names=["redis_key", "increment"],
        )
        return
    with lock:
        client.insert(
            _VELOCITY_COUNTERS_TABLE,
            rows,
            column_names=["redis_key", "increment"],
        )


def clickhouse_configured() -> bool:
    import os

    host = (os.environ.get("CLICKHOUSE_HOST") or "").strip()
    url = (os.environ.get("CLICKHOUSE_URL") or "").strip()
    return bool(host or url)
