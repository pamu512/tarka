"""Event-ingest must fail with a clear diagnosis when NATS lacks JetStream.

A plain ``nats:2-alpine`` broker (no ``-js``) made the container die at startup
with an unhandled ``ServiceUnavailableError`` — an ops mystery instead of an
actionable message. The startup error must name the problem and the fix.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

_SRC = Path(__file__).resolve().parents[1]
for _p in (_SRC / "src", _SRC.parent / "shared"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

os.environ.setdefault("NATS_URL", "nats://127.0.0.1:4222")
os.environ.setdefault("ALLOW_INSECURE_NO_AUTH", "true")
os.environ.pop("API_KEYS", None)


class _NoJetStreamError(Exception):
    pass


def test_jetstream_missing_raises_actionable_error(monkeypatch) -> None:
    import event_ingest.main as m

    class _FakeJS:
        async def find_stream_name_by_subject(self, _subject):
            raise _NoJetStreamError("no JetStream")

        async def add_stream(self, *_a, **_k):
            raise _NoJetStreamError("no JetStream account")

    class _FakeNC:
        def jetstream(self):
            return _FakeJS()

        async def close(self):
            return None

    async def _fake_connect(_url):
        return _FakeNC()

    monkeypatch.setattr(m.nats, "connect", _fake_connect)

    async def _run() -> None:
        try:
            await m._connect_nats()
            raise AssertionError("expected RuntimeError for missing JetStream")
        except RuntimeError as exc:
            assert "JetStream" in str(exc), str(exc)

    asyncio.run(_run())
