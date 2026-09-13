"""Telemetry list must be capped (LTRIM) after every LPUSH.

Bug: ``run_ingest_pipeline`` LPUSHes to ``anumana:browser_telemetry`` with no
LTRIM — an unbounded Redis list if the duck sink is down or undeployed. The cap
keeps sink-down a graceful degradation instead of a slow OOM.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC_ORCH = Path(__file__).resolve().parents[1]
if str(_SRC_ORCH) not in sys.path:
    sys.path.insert(0, str(_SRC_ORCH))

from anumana_velocity import run_ingest_pipeline  # noqa: E402


class _FakePipeline:
    """Collect LPUSH / LTRIM / INCR / EXPIRE ops and replay on execute."""

    def __init__(self, parent: "_FakeRedis") -> None:
        self._parent = parent
        self._ops: list[tuple] = []

    def lpush(self, key: str, value: bytes) -> "_FakePipeline":
        self._ops.append(("lpush", key, value))
        return self

    def ltrim(self, key: str, start: int, stop: int) -> "_FakePipeline":
        self._ops.append(("ltrim", key, (start, stop)))
        return self

    def incr(self, key: str) -> "_FakePipeline":
        self._ops.append(("incr", key, None))
        return self

    def expire(self, key: str, ttl: int) -> "_FakePipeline":
        self._ops.append(("expire", key, ttl))
        return self

    def zadd(self, key: str, mapping: dict[str, float]) -> "_FakePipeline":
        self._ops.append(("zadd", key, mapping))
        return self

    async def execute(self) -> None:
        for op, key, arg in self._ops:
            if op == "lpush":
                self._parent._lists.setdefault(key, []).insert(0, arg)
            elif op == "ltrim":
                start, stop = arg
                lst = self._parent._lists.get(key, [])
                if stop == -1:
                    self._parent._lists[key] = lst[start:]
                else:
                    self._parent._lists[key] = lst[start : stop + 1]
            elif op == "incr":
                self._parent._ints[key] = self._parent._ints.get(key, 0) + 1
            elif op == "zadd":
                self._parent._zsets.setdefault(key, {}).update(arg)


class _FakeRedis:
    """Minimal async Redis fake (lists + counters + zsets), pipeline-aware."""

    def __init__(self) -> None:
        self._lists: dict[str, list[bytes]] = {}
        self._ints: dict[str, int] = {}
        self._zsets: dict[str, dict[str, float]] = {}

    def pipeline(self, transaction: bool = False) -> _FakePipeline:
        _ = transaction
        return _FakePipeline(self)

    async def llen(self, key: str) -> int:
        return len(self._lists.get(key, []))

    async def lindex(self, key: str, index: int) -> bytes | None:
        lst = self._lists.get(key, [])
        if -len(lst) <= index < len(lst):
            return lst[index]
        return None


@pytest.mark.asyncio
async def test_run_ingest_pipeline_trims_telemetry_list_to_cap() -> None:
    r = _FakeRedis()
    for i in range(6):
        await run_ingest_pipeline(
            r,
            stream_key="anumana:browser_telemetry",
            payload_bytes=f'{{"i": {i}}}'.encode(),
            velocity_commands=[],
            session_watch=None,
            telemetry_list_cap=3,
        )
    assert await r.llen("anumana:browser_telemetry") == 3
    head = await r.lindex("anumana:browser_telemetry", 0)
    assert head == b'{"i": 5}'


@pytest.mark.asyncio
async def test_run_ingest_pipeline_cap_disabled_when_zero() -> None:
    r = _FakeRedis()
    for _ in range(4):
        await run_ingest_pipeline(
            r,
            stream_key="anumana:browser_telemetry",
            payload_bytes=b"x",
            velocity_commands=[],
            session_watch=None,
            telemetry_list_cap=0,
        )
    assert await r.llen("anumana:browser_telemetry") == 4
