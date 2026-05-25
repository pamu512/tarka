"""
NATS wrapper for Setu-style OSINT: publish on ``setu.query``, collect reply on a unique inbox.

Typical flow for LLM tools: connect with ``nats.connect(...)``, then
``await nats_setu_osint_lookup(nc, ip="198.51.100.7")``.

Environment:

* ``NATS_URL`` — used by the CLI when no ``--url`` is passed (default ``nats://127.0.0.1:4222``).
* ``SETU_NATS_TIMEOUT_SECONDS`` — default wait for reply (default **15**).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
from typing import TYPE_CHECKING, Any

from shadow.tools.ai_tool_audit import log_ai_tool_nats_osint

logger = logging.getLogger(__name__)

SETU_QUERY_SUBJECT = "setu.query"
_DEFAULT_TIMEOUT_S = 15.0


if TYPE_CHECKING:
    from nats.aio.client import Client as NATSClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _default_timeout() -> float:
    raw = (os.environ.get("SETU_NATS_TIMEOUT_SECONDS") or "").strip()
    if not raw:
        return _DEFAULT_TIMEOUT_S
    try:
        return max(0.1, float(raw))
    except ValueError:
        return _DEFAULT_TIMEOUT_S


def _encode_query_payload(*, ip: str, extra: dict[str, Any] | None = None) -> bytes:
    body: dict[str, Any] = {"kind": "ip_osint", "ip": (ip or "").strip()}
    if extra:
        body.update(extra)
    return json.dumps(body, separators=(",", ":")).encode("utf-8")


def vpn_status_from_osint(payload: dict[str, Any]) -> bool | None:
    """
    Best-effort VPN / hosting signal from a Setu OSINT JSON blob.

    Returns ``True``/``False`` when a boolean-like field is present, else ``None``.
    """
    if not isinstance(payload, dict):
        return None
    for key in ("vpn", "is_vpn", "isVpn"):
        v = payload.get(key)
        if isinstance(v, bool):
            return v
    nested = payload.get("ip_intel") or payload.get("result") or payload.get("data")
    if isinstance(nested, dict):
        return vpn_status_from_osint(nested)
    return None


async def nats_setu_osint_lookup(
    nc: NATSClient,
    *,
    ip: str,
    timeout: float | None = None,
    extra_fields: dict[str, Any] | None = None,
    audit_session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> dict[str, Any]:
    """
    Publish an IP OSINT request to ``setu.query`` with ``reply`` set to a fresh inbox, then await one reply.

    The responder (Setu / integration worker) should ``publish`` JSON OSINT bytes to the ``reply`` subject.

    When ``audit_session_factory`` is set, each attempt is appended to Postgres ``ai_tool_logs`` with the
    **exact** UTF-8 JSON string sent as the NATS payload (``request_payload_exact``) and the raw reply body.
    """
    ip_s = (ip or "").strip()
    if not ip_s:
        raise ValueError("ip must be a non-empty string")

    deadline = _default_timeout() if timeout is None else max(0.1, float(timeout))
    request_bytes = _encode_query_payload(ip=ip_s, extra=extra_fields)
    request_exact = request_bytes.decode("utf-8")

    response_exact: str | None = None
    err: str | None = None
    parsed: dict[str, Any] | None = None

    reply_inbox: str = nc.new_inbox()
    sub = await nc.subscribe(reply_inbox)
    try:
        await nc.flush()
        await nc.publish(SETU_QUERY_SUBJECT, request_bytes, reply=reply_inbox)
        try:
            msg = await asyncio.wait_for(sub.next_msg(), timeout=deadline)
        except TimeoutError as exc:
            err = str(exc)
            raise TimeoutError(
                f"setu OSINT reply timed out after {deadline}s (subject={SETU_QUERY_SUBJECT})",
            ) from exc
        raw = msg.data
        if not raw:
            parsed = {}
            response_exact = ""
            return parsed
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            err = "setu OSINT reply is not valid UTF-8"
            raise ValueError(err) from exc
        response_exact = text
        try:
            loaded: Any = json.loads(text)
        except json.JSONDecodeError as exc:
            err = f"setu OSINT reply is not JSON: {text[:500]!r}"
            raise ValueError(err) from exc
        if not isinstance(loaded, dict):
            err = "setu OSINT reply JSON must be an object at the top level"
            raise ValueError(err)
        parsed = loaded
        return parsed
    finally:
        with contextlib.suppress(Exception):
            await sub.unsubscribe()
        if audit_session_factory is not None:
            await log_ai_tool_nats_osint(
                audit_session_factory,
                tool_name="nats_setu_osint_lookup",
                nats_subject=SETU_QUERY_SUBJECT,
                reply_inbox=reply_inbox,
                request_payload_exact=request_exact,
                response_payload_exact=response_exact,
                error=err,
            )


async def connect_setu_nats(url: str | None = None) -> Any:
    """Connect to NATS (``nats-py``). Caller should ``await nc.drain()`` when finished."""
    import nats

    u = (url or os.environ.get("NATS_URL") or "nats://127.0.0.1:4222").strip()
    return await nats.connect(u)


async def _async_main(argv: list[str] | None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(
        description="Query Setu OSINT over NATS (setu.query + inbox reply)."
    )
    p.add_argument("ip", help="IPv4/IPv6 address to look up")
    p.add_argument(
        "--url",
        default=os.environ.get("NATS_URL") or "nats://127.0.0.1:4222",
        help="NATS server URL (default: NATS_URL env or nats://127.0.0.1:4222)",
    )
    p.add_argument("--timeout", type=float, default=None, help="Reply wait timeout in seconds")
    args = p.parse_args(argv)

    nc = await connect_setu_nats(args.url)
    try:
        data = await nats_setu_osint_lookup(nc, ip=args.ip, timeout=args.timeout)
    finally:
        await nc.drain()

    print(json.dumps(data, indent=2, default=str))
    vpn = vpn_status_from_osint(data)
    if vpn is not None:
        print(f"vpn_status_from_osint: {vpn}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> None:
    raise SystemExit(asyncio.run(_async_main(argv)))


if __name__ == "__main__":
    main()
