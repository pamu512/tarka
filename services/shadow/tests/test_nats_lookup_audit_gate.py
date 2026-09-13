"""Gate (Prompt 135, repointed #10): ``log_ai_tool_nats_osint`` persists exact-payload ``ai_tool_logs`` rows.

Originally gated via the removed ``nats_lookup`` wrapper (``setu.query`` had
zero responders — write-only subject, every prod call timed out). The audit
lane itself is live; this gate exercises it directly.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

_SERVICES = Path(__file__).resolve().parents[2]
if str(_SERVICES) not in sys.path:
    sys.path.insert(0, str(_SERVICES))


def test_ai_tool_logs_row_persists_exact_payloads() -> None:
    from shadow.models.ai_tool_log import AIToolLogORM, Base
    from shadow.tools.ai_tool_audit import log_ai_tool_nats_osint

    async def _run() -> None:
        engine = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        fac = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        request_exact = json.dumps(
            {"kind": "ip_osint", "ip": "198.51.100.200"}, separators=(",", ":")
        )
        response_exact = json.dumps({"ip": "198.51.100.200", "vpn": False}, separators=(",", ":"))

        await log_ai_tool_nats_osint(
            fac,
            tool_name="nats_setu_osint_lookup",
            nats_subject="setu.query",
            reply_inbox="_INBOX.audit_gate",
            request_payload_exact=request_exact,
            response_payload_exact=response_exact,
            error=None,
        )

        async with fac() as session:
            row = (
                await session.execute(
                    select(AIToolLogORM).order_by(AIToolLogORM.id.desc()).limit(1)
                )
            ).scalar_one()
        assert row.request_payload_exact == request_exact
        assert row.response_payload_exact == response_exact
        assert row.nats_subject == "setu.query"
        assert row.tool_name == "nats_setu_osint_lookup"
        assert row.reply_inbox == "_INBOX.audit_gate"
        assert row.error is None

        # DB failures stay swallowed: tool output is primary, audit is best-effort.
        await engine.dispose()
        await log_ai_tool_nats_osint(
            fac,
            tool_name="t",
            nats_subject="s",
            error="boom",
            reply_inbox=None,
            request_payload_exact="{}",
            response_payload_exact=None,
        )

        await engine.dispose()

    asyncio.run(_run())
