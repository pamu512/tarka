"""Gate: audit_logs row + ``integrity_signature`` HMAC; optional live Postgres check."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fakeredis import FakeAsyncRedis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

_SRC = Path(__file__).resolve().parents[1] / "src"
_REPO_ROOT = Path(__file__).resolve().parents[3]
for _p in (_SRC, _REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from signal_api.durable_handover import (  # noqa: E402
    canonical_signal_json_bytes,
    integrity_hmac_sha256_hex,
    verify_integrity_hmac,
)
from signal_api.ingest_handler import router  # noqa: E402


def _body(sid: str) -> dict[str, Any]:
    return {
        "ch": "c" * 64,
        "wv": "ANGLE",
        "dm": 8,
        "ip": "203.0.113.7",
        "px": False,
        "ua": "Mozilla/5.0 (compatible; gate-test)",
        "sid": sid,
        "ts": datetime.now(UTC).isoformat(),
        "sv": "91.0.0",
        "mv": 0.0,
        "tp": 0,
        "hh": False,
    }


class _AuditCapture:
    last_execute: tuple[Any, ...] | None = None


class _FakeConn:
    async def execute(self, query: str, *args: Any) -> str:
        _AuditCapture.last_execute = (query, args)
        return "INSERT 0 1"


class _FakePool:
    def acquire(self) -> Any:
        class _Ctx:
            async def __aenter__(self) -> _FakeConn:
                return _FakeConn()

            async def __aexit__(self, *exc: Any) -> None:
                return None

        return _Ctx()


@pytest.fixture
async def ingester_audit(monkeypatch: pytest.MonkeyPatch) -> AsyncClient:
    monkeypatch.setenv("SYSTEM_SECRET", "gate-secret-unit-test-do-not-reuse")
    app = FastAPI()
    app.state.redis = FakeAsyncRedis(decode_responses=True)
    app.state.audit_pool = _FakePool()
    app.state.nats_js = AsyncMock()
    app.include_router(router, prefix="/v1/signals")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac._test_app = app  # noqa: SLF001
        yield ac


@pytest.mark.anyio
async def test_audit_background_hmac_matches_canonical_payload(ingester_audit: AsyncClient) -> None:
    _AuditCapture.last_execute = None
    sid = "22222222-3333-4444-5555-666666666666"
    body = _body(sid)
    r = await ingester_audit.post("/v1/signals/ingest", json=body)
    assert r.status_code == 201

    # BackgroundTasks run after response; wait for task completion.
    await asyncio.sleep(0.15)

    assert _AuditCapture.last_execute is not None
    _q, args = _AuditCapture.last_execute
    entity_id, raw_payload, decision, integrity_hex = args
    assert isinstance(entity_id, UUID)
    assert decision == "unified_signal.ingested"
    assert isinstance(integrity_hex, str) and len(integrity_hex) == 64

    secret = os.environ["SYSTEM_SECRET"]
    from tarka_v2_core.schemas.ingestion import UnifiedSignalSchema  # noqa: E402

    model = UnifiedSignalSchema.model_validate(raw_payload)
    canon = canonical_signal_json_bytes(model)
    assert verify_integrity_hmac(secret, canon, integrity_hex)

    bad = integrity_hmac_sha256_hex(secret, canon + b"tamper")
    assert not verify_integrity_hmac(secret, canon, bad)

    js = ingester_audit._test_app.state.nats_js  # noqa: SLF001
    js.publish.assert_awaited_once()
    pub_args, pub_kwargs = js.publish.call_args
    assert pub_args[0] == "signals.raw"
    assert pub_args[1] == canon


@pytest.mark.anyio
async def test_postgres_audit_row_matches_hmac_optional_live_pg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dsn = (os.environ.get("SIGNAL_GATE_PG_URL") or "").strip()
    if not dsn:
        pytest.skip("Set SIGNAL_GATE_PG_URL for live Postgres gate (see signal-api README pattern).")

    monkeypatch.setenv("SYSTEM_SECRET", "live-gate-secret-do-not-reuse")

    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_logs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                entity_id UUID NOT NULL,
                raw_payload JSONB NOT NULL,
                decision VARCHAR(512) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                integrity_signature VARCHAR(128)
            )
            """
        )
        await conn.execute("TRUNCATE audit_logs")
    finally:
        await conn.close()

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)

    app = FastAPI()
    app.state.redis = FakeAsyncRedis(decode_responses=True)
    app.state.audit_pool = pool
    app.state.nats_js = None
    app.include_router(router, prefix="/v1/signals")
    transport = ASGITransport(app=app)

    sid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    payload = _body(sid)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/v1/signals/ingest", json=payload)
        assert r.status_code == 201

    await asyncio.sleep(0.2)
    await pool.close()

    conn2 = await asyncpg.connect(dsn)
    try:
        row = await conn2.fetchrow(
            """
            SELECT raw_payload, integrity_signature, created_at
            FROM audit_logs
            ORDER BY created_at DESC
            LIMIT 1
            """
        )
        assert row is not None
        raw = row["raw_payload"]
        sig = row["integrity_signature"]
        ts = row["created_at"]
        assert ts is not None
        assert isinstance(sig, str) and len(sig) == 64

        from tarka_v2_core.schemas.ingestion import UnifiedSignalSchema  # noqa: E402

        model = UnifiedSignalSchema.model_validate(dict(raw))
        canon = canonical_signal_json_bytes(model)
        assert verify_integrity_hmac(
            os.environ["SYSTEM_SECRET"],
            canon,
            sig,
        )
    finally:
        await conn2.close()
