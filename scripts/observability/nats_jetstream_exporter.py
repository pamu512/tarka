#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

"""
Stretch: NATS JetStream → Prometheus text (pull model).

Polls JetStream stream/consumer stats via NATS and prints Prometheus exposition format.
Run alongside your stack or in cron; scrape with Prometheus ``file_sd`` or pushgateway.

Usage::

  NATS_URL=nats://localhost:4222 \\
  NATS_STREAM_NAME=tarka-events \\
  python scripts/observability/nats_jetstream_exporter.py

Env:
  NATS_URL (required)
  NATS_STREAM_NAME (default: tarka-events)
  NATS_CONSUMER_NAME (optional durable name for pending/ack metrics)
"""


async def _run() -> str:
    import nats  # type: ignore

    url = os.environ.get("NATS_URL", "nats://localhost:4222").strip()
    stream = os.environ.get("NATS_STREAM_NAME", "tarka-events").strip()
    consumer = os.environ.get("NATS_CONSUMER_NAME", "").strip()
    nc = await nats.connect(url)
    try:
        js = nc.jetstream()
        info = await js.stream_info(stream)
        lines: list[str] = []
        lines.append("# HELP nats_jetstream_messages_total Approximate stream message count")
        lines.append("# TYPE nats_jetstream_messages_total gauge")
        state = getattr(info, "state", None) or {}
        msgs = getattr(state, "messages", None) if not isinstance(state, dict) else state.get("messages")
        if msgs is None:
            msgs = 0
        lines.append(f'nats_jetstream_messages_total{{stream="{stream}"}} {int(msgs)}')

        if consumer:
            cinfo = await js.consumer_info(stream, consumer)
            pending = getattr(cinfo, "num_pending", None)
            if pending is None and isinstance(cinfo, dict):
                pending = cinfo.get("num_pending", 0)
            lines.append("# HELP nats_jetstream_consumer_pending_messages Pending messages for consumer")
            lines.append("# TYPE nats_jetstream_consumer_pending_messages gauge")
            lines.append(f'nats_jetstream_consumer_pending_messages{{stream="{stream}",consumer="{consumer}"}} {int(pending or 0)}')
        return "\n".join(lines) + "\n"
    finally:
        await nc.drain()


def main() -> int:
    import asyncio

    try:
        out = asyncio.run(_run())
    except Exception as e:
        print(f"# ERROR {e}", file=sys.stderr)
        return 1
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
