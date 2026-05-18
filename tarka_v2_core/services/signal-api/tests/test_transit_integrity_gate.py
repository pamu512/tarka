"""Gate: client ``ih`` + ``n`` verified server-side; Postgres ``decision`` = ``TAMPERED_IN_TRANSIT`` on mismatch."""

from __future__ import annotations

import asyncio
import hashlib
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
_REPO = Path(__file__).resolve().parents[4]
for _p in (_SRC, _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from signal_api.ingest_handler import router as ingest_router  # noqa: E402
from signal_api.session_nonce import router as session_router  # noqa: E402
from signal_api.transit_integrity import canonical_transit_wire_bytes  # noqa: E402
from tarka_v2_core.schemas.ingestion import UnifiedSignalSchema  # noqa: E402


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


def _wire_core(sid: str) -> dict[str, Any]:
    return {
        "ch": "e" * 64,
        "wv": "wv",
        "dm": 8,
        "ip": "198.51.100.55",
        "px": False,
        "ua": "Mozilla/5.0 (transit-gate)",
        "sid": sid,
        "ts": datetime.now(UTC).isoformat(),
        "sv": "94.0.0",
        "mv": 0.0,
        "tp": 0,
        "hh": False,
    }


@pytest.fixture
async def signal_app(monkeypatch: pytest.MonkeyPatch) -> AsyncClient:
    monkeypatch.setenv("SYSTEM_SECRET", "transit-gate-secret")
    app = FastAPI()
    app.state.redis = FakeAsyncRedis(decode_responses=True)
    app.state.audit_pool = _FakePool()
    app.state.nats_js = AsyncMock()
    app.include_router(session_router, prefix="/v1/session")
    app.include_router(ingest_router, prefix="/v1/signals")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac._test_app = app  # noqa: SLF001
        yield ac


@pytest.mark.anyio
async def test_matching_client_hash_ingested_not_tampered(signal_app: AsyncClient) -> None:
    _AuditCapture.last_execute = None
    sid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    nr = await signal_app.post("/v1/session/nonce", json={"session_id": sid})
    assert nr.status_code == 200
    nonce = nr.json()["nonce"]

    core = _wire_core(sid)
    m0 = UnifiedSignalSchema.model_validate(core)
    exp = hashlib.sha256(canonical_transit_wire_bytes(m0) + b"|" + nonce.encode("utf-8")).hexdigest()
    body = {**core, "n": nonce, "ih": exp}

    r = await signal_app.post("/v1/signals/ingest", json=body)
    assert r.status_code == 201
    await asyncio.sleep(0.15)
    assert _AuditCapture.last_execute is not None
    _q, args = _AuditCapture.last_execute
    decision = args[2]
    assert decision == "unified_signal.ingested"


@pytest.mark.anyio
async def test_wrong_client_hash_marked_tampered_in_transit_postgres(signal_app: AsyncClient) -> None:
    _AuditCapture.last_execute = None
    sid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    nr = await signal_app.post("/v1/session/nonce", json={"session_id": sid})
    nonce = nr.json()["nonce"]

    body = {**_wire_core(sid), "n": nonce, "ih": "0" * 64}
    r = await signal_app.post("/v1/signals/ingest", json=body)
    assert r.status_code == 201
    await asyncio.sleep(0.15)
    assert _AuditCapture.last_execute is not None
    _q, args = _AuditCapture.last_execute
    decision = args[2]
    assert decision == "TAMPERED_IN_TRANSIT"
    assert isinstance(args[1], dict)
    assert args[0] == UUID(sid)
