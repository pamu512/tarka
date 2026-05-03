"""Redis Streams ingestion helpers for data-platform."""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis


async def ensure_group(redis: aioredis.Redis, stream: str, group: str) -> None:
    try:
        await redis.xgroup_create(stream, group, id="$", mkstream=True)
    except Exception as exc:
        # BUSYGROUP means group already exists.
        if "BUSYGROUP" not in str(exc):
            raise


async def publish_event(redis: aioredis.Redis, stream: str, event: dict[str, Any]) -> str:
    payload = {"event": json.dumps(event, default=str)}
    return await redis.xadd(stream, payload, maxlen=1_000_000, approximate=True)


def parse_stream_event(fields: dict[Any, Any]) -> dict[str, Any]:
    raw = fields.get("event")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            return {}
    return {}

