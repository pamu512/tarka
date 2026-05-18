"""Gate: ``POST /ingest`` LPUSHes browser telemetry JSON to Redis (Anumana hot path)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from starlette.testclient import TestClient

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
for _p in (_SRC_ORCH, _SRC_INGESTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


class _FakePipeline:
    """Minimal redis.asyncio pipeline stand-in for ``LPUSH`` + ``INCR`` + ``EXPIRE`` + ``ZADD``."""

    def __init__(self, parent: "_FakeRedis") -> None:
        self._parent = parent
        self._ops: list[tuple[str, ...]] = []

    def lpush(self, key: str, value: bytes) -> None:
        self._ops.append(("lpush", key, value))

    def incr(self, key: str) -> None:
        self._ops.append(("incr", key))

    def expire(self, key: str, ttl: int) -> None:
        self._ops.append(("expire", key, ttl))

    def zadd(self, key: str, mapping: dict) -> None:
        self._ops.append(("zadd", key, mapping))

    async def execute(self) -> list[int]:
        out: list[int] = []
        for op in self._ops:
            if op[0] == "lpush":
                await self._parent.lpush(op[1], op[2])
                out.append(1)
            elif op[0] == "incr":
                n = await self._parent.incr(op[1])
                out.append(n)
            elif op[0] == "expire":
                self._parent.expires.append((op[1], int(op[2])))
                out.append(1)
            elif op[0] == "zadd":
                n = await self._parent.zadd(op[1], op[2])
                out.append(n)
        return out


class _FakeRedis:
    def __init__(self) -> None:
        self.pushes: list[tuple[str, bytes]] = []
        self.incrs: list[str] = []
        self.expires: list[tuple[str, int]] = []
        self.strings: dict[str, str] = {}
        self.zsets: dict[str, dict[str, float]] = {}

    def pipeline(self, transaction: bool = False) -> _FakePipeline:
        _ = transaction
        return _FakePipeline(self)

    async def lpush(self, key: str, value: bytes) -> int:
        self.pushes.append((key, value))
        return 1

    async def incr(self, key: str) -> int:
        self.incrs.append(key)
        cur = int(self.strings.get(key, "0")) + 1
        self.strings[key] = str(cur)
        return cur

    async def zadd(self, key: str, mapping: dict) -> int:
        slot = self.zsets.setdefault(key, {})
        for mk, score in mapping.items():
            mk_s = mk.decode("utf-8") if isinstance(mk, bytes) else str(mk)
            slot[mk_s] = float(score)
        return len(mapping)

    async def aclose(self) -> None:
        return None


def test_post_ingest_lpush_canvas_and_ingress_ip() -> None:
    from orchestrator.main import create_app  # noqa: E402

    fake = _FakeRedis()
    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        anumana_redis_client=fake,
    )
    with TestClient(app) as client:
        r = client.post(
            "/ingest",
            json={
                "canvas_fingerprint": "ab" * 32,
                "ip": "192.0.2.1",
                "tenant_id": "t1",
                "device_session_id": "sess-9",
            },
            headers={"X-Forwarded-For": "198.51.100.9, 10.0.0.1"},
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("accepted") is True
    assert data.get("velocity_updates") == 9
    assert len(fake.pushes) == 1
    key, raw = fake.pushes[0]
    assert key == "anumana:browser_telemetry"
    env = json.loads(raw.decode("utf-8"))
    assert env["schema"] == "tarka.browser_telemetry.v1"
    assert env["ingress_ip"] == "198.51.100.9"
    assert env["client_claimed_ip"] == "192.0.2.1"
    assert env["canvas_fingerprint"] == "ab" * 32
    assert len(fake.incrs) == 10
    assert len(fake.expires) == 9
    assert any(":device:1m:" in k for k in fake.incrs)
    assert any(":ip:1h:" in k for k in fake.incrs)
    from orchestrator.anumana_session_watch import session_watch_member  # noqa: E402

    m = session_watch_member("t1", "sess-9")
    assert m in fake.zsets.get("anumana:session_watch", {})


def test_post_ingest_requires_auth_when_secret_set(monkeypatch) -> None:
    from orchestrator.main import create_app  # noqa: E402

    monkeypatch.setenv("ANUMANA_TELEMETRY_INGEST_KEY", "secret-99")
    fake = _FakeRedis()
    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        anumana_redis_client=fake,
    )
    with TestClient(app) as client:
        r = client.post(
            "/ingest",
            json={"canvas_fingerprint": "aa" * 32},
        )
    assert r.status_code == 401
    assert fake.pushes == []
