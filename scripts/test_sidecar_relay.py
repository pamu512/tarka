#!/usr/bin/env python3
"""
Integration probe: POST /v1/decide → Redis ``tarka:decisions_stream`` → ml_sidecar relay key.

Exits 0 only when, within RELAY_TEST_TIMEOUT_SEC (default 2s) after a successful HTTP 200:
  1) The stream contains an entry for the test ``entity_id``.
  2) Redis key ``tarka:relay:processed:<entity_id>`` is set by ml_sidecar after processing.

Requires:
  - Core API (``CORE_API_URL``, default http://127.0.0.1:8000)
  - Redis (``REDIS_URL``, default redis://127.0.0.1:6379/0)
  - ml_sidecar running with the same Redis (writes relay key on successful scoring)

Install: pip install aiohttp redis

Usage:
  export CORE_API_URL=http://127.0.0.1:8000
  export REDIS_URL=redis://127.0.0.1:6379/0
  python scripts/test_sidecar_relay.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime

import aiohttp
import redis.asyncio as redis

STREAM_NAME = "tarka:decisions_stream"
RELAY_PREFIX = os.environ.get("RELAY_PROCESSED_KEY_PREFIX", "tarka:relay:processed:")
CORE_API_URL = os.environ.get("CORE_API_URL", "http://127.0.0.1:8000").rstrip("/")
REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
RELAY_TEST_TIMEOUT_SEC = float(os.environ.get("RELAY_TEST_TIMEOUT_SEC", "2.0"))
POLL_INTERVAL_SEC = float(os.environ.get("RELAY_POLL_INTERVAL_SEC", "0.05"))


async def _stream_contains_entity(client: redis.Redis, entity_str: str) -> bool:
    """True if a recent stream entry references ``entity_str`` (flat fields or JSON payload)."""
    entries = await client.xrevrange(STREAM_NAME, max="+", min="-", count=500)
    for _mid, fields in entries:
        if fields.get("entity_id") == entity_str:
            return True
        payload_raw = fields.get("payload")
        if payload_raw:
            try:
                obj = json.loads(payload_raw)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and str(obj.get("entity_id")) == entity_str:
                return True
    return False


async def run_probe() -> int:
    entity = uuid.uuid4()
    entity_str = str(entity)
    payload = {
        "entity_id": entity_str,
        "amount": 5000.0,
        "timestamp": datetime.now(UTC).isoformat(),
        "metadata": {"relay_integration_test": True},
    }

    redis_client = redis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=5.0,
    )
    try:
        timeout = aiohttp.ClientTimeout(total=30.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{CORE_API_URL}/v1/decide",
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as resp:
                body = await resp.text()
                if resp.status != 200:
                    print(
                        json.dumps(
                            {
                                "status": "http_error",
                                "http_status": resp.status,
                                "body": body[:500],
                            }
                        ),
                        file=sys.stderr,
                    )
                    return 1

        deadline = time.monotonic() + RELAY_TEST_TIMEOUT_SEC
        relay_key = f"{RELAY_PREFIX}{entity_str}"

        stream_ok = False
        relay_ok = False

        while time.monotonic() < deadline:
            if not stream_ok:
                stream_ok = await _stream_contains_entity(redis_client, entity_str)
            if not relay_ok:
                relay_ok = bool(await redis_client.get(relay_key))

            if stream_ok and relay_ok:
                print(
                    json.dumps(
                        {
                            "status": "ok",
                            "entity_id": entity_str,
                            "stream_verified": True,
                            "sidecar_relay_key_set": True,
                            "relay_key": relay_key,
                        },
                        separators=(",", ":"),
                    )
                )
                return 0

            await asyncio.sleep(POLL_INTERVAL_SEC)

        print(
            json.dumps(
                {
                    "status": "timeout",
                    "entity_id": entity_str,
                    "stream_verified": stream_ok,
                    "sidecar_relay_verified": relay_ok,
                    "timeout_sec": RELAY_TEST_TIMEOUT_SEC,
                },
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        await redis_client.aclose()


def main() -> None:
    raise SystemExit(asyncio.run(run_probe()))


if __name__ == "__main__":
    main()
