"""Gate (Prompt 129): ``nats_setu_osint_lookup`` publishes ``setu.query`` + inbox reply; VPN field is readable."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

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
    """Minimal stand-in for ``nats.NATS``: records ``publish`` and returns a canned inbox reply."""

    def __init__(self, reply_obj: dict[str, Any]) -> None:
        self._body = json.dumps(reply_obj).encode()
        self.published: list[tuple[str, bytes, str]] = []
        self._inbox: str = "_INBOX.unset"

    def new_inbox(self) -> str:
        self._inbox = "_INBOX.shadow_gate_129"
        return self._inbox

    async def flush(self) -> None:
        return None

    async def subscribe(self, subject: str) -> _FakeSub:
        assert subject == self._inbox
        return _FakeSub(self._body)

    async def publish(self, subject: str, payload: bytes, reply: str = "") -> None:
        self.published.append((subject, payload, reply))


def test_nats_setu_osint_lookup_returns_vpn_for_test_ip() -> None:
    """Manual-style gate without a broker: assert wire shape + ``vpn`` extraction for TEST-NET-3 IP."""
    from shadow.tools.nats_lookup import (
        SETU_QUERY_SUBJECT,
        nats_setu_osint_lookup,
        vpn_status_from_osint,
    )

    test_ip = "198.51.100.99"
    reply = {"ip": test_ip, "vpn": True, "source": "gate-stub-setu"}

    async def _run() -> None:
        fake = FakeNatsClient(reply)
        out = await nats_setu_osint_lookup(fake, ip=test_ip, timeout=2.0)
        assert vpn_status_from_osint(out) is True
        assert len(fake.published) == 1
        subj, body, rply = fake.published[0]
        assert subj == SETU_QUERY_SUBJECT
        assert rply == "_INBOX.shadow_gate_129"
        req = json.loads(body.decode())
        assert req["kind"] == "ip_osint"
        assert req["ip"] == test_ip

    asyncio.run(_run())
