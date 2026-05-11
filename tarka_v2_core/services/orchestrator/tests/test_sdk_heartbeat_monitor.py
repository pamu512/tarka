"""SDK heartbeat monitor: stale session → Redis ``HIGH_RISK_DROPOFF`` flag."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
for _p in (_SRC_ORCH, _SRC_INGESTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from orchestrator.anumana_session_watch import (  # noqa: E402
    scan_stale_sessions_for_dropoff,
    session_event_count_key,
    session_risk_flag_key,
    session_watch_member,
    session_watch_zset_key,
)


def _bound(x: float | str) -> float:
    if isinstance(x, (int, float)):
        return float(x)
    if x == "-inf":
        return float("-inf")
    if x == "+inf":
        return float("inf")
    return float(x)


class _FakePipeline:
    def __init__(self, parent: "_FakeRedisHeartbeat") -> None:
        self._parent = parent
        self._ops: list[tuple] = []

    def set(self, key: str, value: str | bytes, ex: int | None = None) -> None:
        self._ops.append(("set", key, value, ex))

    def zrem(self, key: str, member: str | bytes) -> None:
        self._ops.append(("zrem", key, member))

    def delete(self, key: str) -> None:
        self._ops.append(("delete", key))

    async def execute(self) -> list:
        out: list = []
        for op in self._ops:
            if op[0] == "set":
                _, key, value, ex = op
                await self._parent.set(key, value, ex=ex)
                out.append(True)
            elif op[0] == "zrem":
                n = await self._parent.zrem(op[1], op[2])
                out.append(n)
            elif op[0] == "delete":
                n = await self._parent.delete(op[1])
                out.append(n)
        return out


class _FakeRedisHeartbeat:
    zkey = session_watch_zset_key()

    def __init__(self) -> None:
        self.zsets: dict[str, dict[str, float]] = {}
        self.strings: dict[str, bytes] = {}

    def pipeline(self, transaction: bool = False) -> _FakePipeline:
        _ = transaction
        return _FakePipeline(self)

    async def zrangebyscore(
        self,
        key: str,
        min_s: str | float,
        max_s: str | float,
        start: int | None = None,
        num: int | None = None,
    ) -> list[bytes]:
        lo = _bound(min_s)
        hi = _bound(max_s)
        z = self.zsets.get(key, {})
        pairs = [(m, sc) for m, sc in z.items() if lo <= sc <= hi]
        pairs.sort(key=lambda x: x[1])
        ms = [p[0] for p in pairs]
        if start is not None:
            ms = ms[int(start) :]
        if num is not None:
            ms = ms[: int(num)]
        return [m.encode("utf-8") if isinstance(m, str) else m for m in ms]

    async def get(self, key: str) -> bytes | None:
        return self.strings.get(key)

    async def set(self, key: str, value: str | bytes, ex: int | None = None) -> bool:
        _ = ex
        b = value if isinstance(value, bytes) else value.encode("utf-8")
        self.strings[key] = b
        return True

    async def zrem(self, key: str, member: str | bytes) -> int:
        m = member.decode("utf-8") if isinstance(member, bytes) else member
        z = self.zsets.get(key)
        if not z or m not in z:
            return 0
        del z[m]
        return 1

    async def delete(self, key: str) -> int:
        return 1 if self.strings.pop(key, None) is not None else 0


def test_scan_flags_high_risk_dropoff_when_silent_mid_session() -> None:
    async def _run() -> None:
        r = _FakeRedisHeartbeat()
        m = session_watch_member("tenant-a", "sess-drop")
        r.zsets[r.zkey] = {m: 100.0}
        r.strings[session_event_count_key(m)] = b"3"

        with patch("orchestrator.anumana_session_watch.time") as mt:
            mt.time.return_value = 400.0
            stats = await scan_stale_sessions_for_dropoff(
                r,
                silence_sec=120.0,
                min_events=2,
                flag_ttl_sec=3600,
                batch_limit=50,
            )

        assert stats == {"scanned": 1, "flagged": 1, "cleared_young": 0}
        rk = session_risk_flag_key(m)
        assert r.strings[rk] == b"HIGH_RISK_DROPOFF"
        assert m not in r.zsets.get(r.zkey, {})
        assert session_event_count_key(m) not in r.strings

    asyncio.run(_run())


def test_scan_clears_single_event_without_flag() -> None:
    async def _run() -> None:
        r = _FakeRedisHeartbeat()
        m = session_watch_member("_", "sess-once")
        r.zsets[r.zkey] = {m: 50.0}
        r.strings[session_event_count_key(m)] = b"1"

        with patch("orchestrator.anumana_session_watch.time") as mt:
            mt.time.return_value = 400.0
            stats = await scan_stale_sessions_for_dropoff(
                r,
                silence_sec=60.0,
                min_events=2,
                flag_ttl_sec=3600,
                batch_limit=50,
            )

        assert stats["flagged"] == 0
        assert stats["cleared_young"] == 1
        assert session_risk_flag_key(m) not in r.strings
        assert m not in r.zsets.get(r.zkey, {})

    asyncio.run(_run())


def test_session_watch_member_stable() -> None:
    m = session_watch_member("t1", "abc")
    assert "\x1f" in m
    assert m.endswith("abc")
