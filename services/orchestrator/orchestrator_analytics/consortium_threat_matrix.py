"""Global consortium threat-matrix counters (Redis + ClickHouse mirror)."""

from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass
from typing import Any

from messaging.labels_jetstream import NORMALIZED_LABEL_EVENT_SCHEMA

logger = logging.getLogger(__name__)

_TAG_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_]*:[a-z][a-z0-9_]{0,63}$")
_CONSORTIUM_THREAT_COUNTERS_TABLE = "orchestrator_consortium_threat_counters"
_CONSORTIUM_THREAT_LABEL_DEDUPE_TABLE = "orchestrator_consortium_threat_label_dedupe"
_DDL = f"""
CREATE TABLE IF NOT EXISTS {_CONSORTIUM_THREAT_COUNTERS_TABLE} (
    redis_key String,
    increment Int64
) ENGINE = SummingMergeTree
ORDER BY (redis_key)
"""
_DEDUPE_DDL = f"""
CREATE TABLE IF NOT EXISTS {_CONSORTIUM_THREAT_LABEL_DEDUPE_TABLE} (
    label_id String,
    applied_at DateTime64(3) DEFAULT now64(3)
) ENGINE = ReplacingMergeTree(applied_at)
ORDER BY (label_id)
"""


class ConsortiumThreatMatrixError(ValueError):
    """Raised when a normalized label event cannot be applied to the threat matrix."""


@dataclass(frozen=True, slots=True)
class ConsortiumThreatCounterCommand:
    """One Redis ``INCRBY`` and matching ClickHouse SummingMergeTree delta."""

    redis_key: str
    increment: int


def consortium_threat_matrix_key_prefix() -> str:
    return (
        os.environ.get("CONSORTIUM_THREAT_MATRIX_KEY_PREFIX") or "anumana:consortium:threat"
    ).strip() or "anumana:consortium:threat"


def consortium_id_from_environment() -> str:
    token = (os.environ.get("CONSORTIUM_ID") or "global").strip()
    if not token or len(token) > 128 or "\x00" in token:
        return "global"
    return token


def _normalize_ground_truth_class(raw: object) -> str:
    token = str(raw or "").strip().upper()
    if token not in {"FRAUD", "LEGITIMATE"}:
        raise ConsortiumThreatMatrixError(
            f"ground_truth_class must be FRAUD or LEGITIMATE, got {raw!r}"
        )
    return token


def _normalize_label_id(raw: object) -> str:
    token = str(raw or "").strip()
    if not token or len(token) > 128:
        raise ConsortiumThreatMatrixError("label event id is required")
    return token


def _normalize_structural_tag(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    token = raw.strip().lower()
    if not token or not _TAG_TOKEN_RE.fullmatch(token):
        return None
    return token


_CONSORTIUM_APPLIED_LABELS_HASH_SUFFIX = ":applied_labels"


def applied_labels_redis_key(*, consortium_id: str) -> str:
    prefix = consortium_threat_matrix_key_prefix()
    cid = (consortium_id or "global").strip() or "global"
    return f"{prefix}:cid:{cid}{_CONSORTIUM_APPLIED_LABELS_HASH_SUFFIX}"


_APPLY_LABEL_COUNTERS_LUA = """
local applied_hash = KEYS[1]
local label_id = ARGV[1]
if redis.call('HEXISTS', applied_hash, label_id) == 1 then
  return 0
end
redis.call('HSET', applied_hash, label_id, '1')
local idx = 2
while idx <= #ARGV do
  redis.call('incrby', ARGV[idx], tonumber(ARGV[idx + 1]))
  idx = idx + 2
end
return 1
"""


def build_consortium_threat_counter_commands(
    label_entity: dict[str, Any],
    *,
    consortium_id: str | None = None,
) -> tuple[str, list[ConsortiumThreatCounterCommand]]:
    """
    Derive atomic counter increments for one enriched ``tarka.normalized_label.v1`` event.

    Returns ``(label_id, commands)``.
    """
    if not isinstance(label_entity, dict):
        raise ConsortiumThreatMatrixError("label_entity must be a dict")
    if label_entity.get("schema") != NORMALIZED_LABEL_EVENT_SCHEMA:
        raise ConsortiumThreatMatrixError(
            f"unsupported label event schema: {label_entity.get('schema')!r}",
        )
    if not bool(label_entity.get("propagated_to_consortium")):
        raise ConsortiumThreatMatrixError("label event must have propagated_to_consortium=true")

    label_id = _normalize_label_id(label_entity.get("id"))
    ground_truth = _normalize_ground_truth_class(label_entity.get("ground_truth_class"))
    cid = (consortium_id or consortium_id_from_environment()).strip() or "global"
    prefix = consortium_threat_matrix_key_prefix()

    commands: list[ConsortiumThreatCounterCommand] = [
        ConsortiumThreatCounterCommand(
            redis_key=f"{prefix}:cid:{cid}:ground_truth:{ground_truth}",
            increment=1,
        ),
        ConsortiumThreatCounterCommand(
            redis_key=f"{prefix}:cid:{cid}:labels_total",
            increment=1,
        ),
    ]

    tags_raw = label_entity.get("tags")
    if not isinstance(tags_raw, list):
        raise ConsortiumThreatMatrixError("label event tags must be a list")

    seen_tags: set[str] = set()
    for raw_tag in tags_raw:
        tag = _normalize_structural_tag(raw_tag)
        if tag is None or tag in seen_tags:
            continue
        seen_tags.add(tag)
        ns, _, value = tag.partition(":")
        commands.append(
            ConsortiumThreatCounterCommand(
                redis_key=f"{prefix}:cid:{cid}:tag:{ns}:{value}",
                increment=1,
            ),
        )
        commands.append(
            ConsortiumThreatCounterCommand(
                redis_key=f"{prefix}:cid:{cid}:tag:{ns}:{value}:gt:{ground_truth}",
                increment=1,
            ),
        )

    return label_id, commands


async def apply_consortium_threat_counter_increments(
    redis_client: Any,
    commands: list[ConsortiumThreatCounterCommand],
    *,
    consortium_id: str,
    label_id: str,
) -> bool:
    """
    Atomically apply threat-matrix ``INCRBY`` operations for one label.

    Returns ``True`` when Redis counters were incremented, ``False`` when the label was already applied.
    """
    if not commands:
        return False
    applied_hash = applied_labels_redis_key(consortium_id=consortium_id)
    argv: list[str | int] = [label_id]
    for cmd in commands:
        argv.extend([cmd.redis_key, int(cmd.increment)])

    script = redis_client.register_script(_APPLY_LABEL_COUNTERS_LUA)
    raw = await script(keys=[applied_hash], args=argv)
    if raw is None:
        raise RuntimeError("redis threat-matrix script returned None")
    try:
        applied = int(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"redis threat-matrix script returned non-integer: {raw!r}") from exc
    if applied not in (0, 1):
        raise RuntimeError(f"redis threat-matrix script returned unexpected code: {applied}")
    return applied == 1


async def verify_consortium_threat_counter_increments(
    redis_client: Any,
    commands: list[ConsortiumThreatCounterCommand],
) -> list[int]:
    """Read back counter values after ``INCRBY`` to verify Redis execution."""
    if not commands:
        return []
    pipe = redis_client.pipeline(transaction=False)
    for cmd in commands:
        pipe.get(cmd.redis_key)
    raw_results = await pipe.execute()
    if not isinstance(raw_results, list) or len(raw_results) != len(commands):
        raise RuntimeError("redis GET verification returned unexpected result count")
    verified: list[int] = []
    for idx, raw in enumerate(raw_results):
        if raw is None:
            raise RuntimeError(
                f"redis counter missing after increment: {commands[idx].redis_key!r}"
            )
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"redis counter {commands[idx].redis_key!r} has non-integer value: {raw!r}",
            ) from exc
        if value < commands[idx].increment:
            raise RuntimeError(
                f"redis counter verification failed for {commands[idx].redis_key!r}: "
                f"expected >= {commands[idx].increment}, got {value}",
            )
        verified.append(value)
    return verified


def ensure_consortium_threat_counters_table(client: Any) -> None:
    client.command(_DDL)
    client.command(_DEDUPE_DDL)


def consortium_threat_label_already_applied_clickhouse(client: Any, label_id: str) -> bool:
    safe_id = label_id.replace("'", "''")
    rows = client.query(
        f"SELECT 1 FROM {_CONSORTIUM_THREAT_LABEL_DEDUPE_TABLE} FINAL WHERE label_id = '{safe_id}' LIMIT 1",
    ).result_rows
    return bool(rows)


def apply_consortium_threat_counter_increments_clickhouse(
    client: Any,
    commands: list[ConsortiumThreatCounterCommand],
    *,
    label_id: str,
    lock: threading.Lock | None = None,
) -> None:
    """Insert SummingMergeTree rows mirroring Redis ``INCRBY`` deltas (idempotent per label_id)."""
    if consortium_threat_label_already_applied_clickhouse(client, label_id):
        return
    if not commands:
        client.insert(
            _CONSORTIUM_THREAT_LABEL_DEDUPE_TABLE,
            [[label_id]],
            column_names=["label_id"],
        )
        return

    def _insert() -> None:
        client.insert(
            _CONSORTIUM_THREAT_LABEL_DEDUPE_TABLE,
            [[label_id]],
            column_names=["label_id"],
        )
        rows = [[cmd.redis_key, int(cmd.increment)] for cmd in commands]
        client.insert(
            _CONSORTIUM_THREAT_COUNTERS_TABLE,
            rows,
            column_names=["redis_key", "increment"],
        )

    if lock is None:
        _insert()
        return
    with lock:
        _insert()


def clickhouse_configured() -> bool:
    host = (os.environ.get("CLICKHOUSE_HOST") or "").strip()
    url = (os.environ.get("CLICKHOUSE_URL") or "").strip()
    return bool(host or url)
