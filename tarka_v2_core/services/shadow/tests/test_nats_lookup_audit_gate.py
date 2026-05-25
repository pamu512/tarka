"""Gate (Prompt 135): NATS OSINT tool writes ``ai_tool_logs`` with exact request JSON."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

_SERVICES = Path(__file__).resolve().parents[2]
if str(_SERVICES) not in sys.path:
    sys.path.insert(0, str(_SERVICES))


class _FakeMsg:
    __slots__ = ("data",)

    def __init__(self, data: bytes) -> None:
        self.data = data


class _FakeSub:
    def __init__(self, body: bytes) -> None:
        self._body = body

    async def next_msg(self, timeout: float | None = None) -> _FakeMsg:
        _ = timeout
        return _FakeMsg(self._body)

    async def unsubscribe(self) -> None:
        return None


class FakeNatsClient:
    def __init__(self, reply_obj: dict[str, Any]) -> None:
        self._body = json.dumps(reply_obj, separators=(",", ":")).encode()
        self._inbox = "_INBOX.audit_gate"

    def new_inbox(self) -> str:
        return self._inbox

    async def flush(self) -> None:
        return None

    async def subscribe(self, subject: str) -> _FakeSub:
        return _FakeSub(self._body)

    async def publish(self, subject: str, payload: bytes, reply: str = "") -> None:
        _ = subject, reply
        self.last_payload = payload

    async def drain(self) -> None:
        return None


def test_ai_tool_logs_request_payload_matches_wire_json_exactly() -> None:
    from shadow.models.ai_tool_log import AIToolLogORM, Base
    from shadow.tools.nats_lookup import nats_setu_osint_lookup

    async def _run() -> None:
        engine = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        test_ip = "198.51.100.200"
        expected_request = json.dumps({"kind": "ip_osint", "ip": test_ip}, separators=(",", ":"))

        reply = {"ip": test_ip, "vpn": False, "source": "audit-gate"}
        nc = FakeNatsClient(reply)

        out = await nats_setu_osint_lookup(nc, ip=test_ip, timeout=2.0, audit_session_factory=fac)
        assert out["vpn"] is False
        assert nc.last_payload.decode() == expected_request

        async with fac() as session:
            row = (
                await session.execute(
                    select(AIToolLogORM).order_by(AIToolLogORM.id.desc()).limit(1)
                )
            ).scalar_one()
        assert row.request_payload_exact == expected_request
        assert row.nats_subject == "setu.query"
        assert row.tool_name == "nats_setu_osint_lookup"
        assert row.reply_inbox == "_INBOX.audit_gate"
        assert row.error is None
        assert row.response_payload_exact == nc._body.decode()

        await engine.dispose()

    asyncio.run(_run())
