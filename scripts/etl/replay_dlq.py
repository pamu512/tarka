#!/usr/bin/env python3
"""Pull messages from JetStream DLQ subject `fraud.events.dlq` (same stream as main ingest).

Requires: pip install nats-py httpx (or run from repo venv with event-ingest deps).

Examples:
  NATS_URL=nats://localhost:4222 DECISION_API_URL=http://localhost:8000 \\
    python scripts/etl/replay_dlq.py --max 10 --dry-run

  # Actually POST evaluate bodies from dlq.envelope.original (dangerous — use non-prod only)
  NATS_URL=nats://localhost:4222 DECISION_API_URL=http://localhost:8000 \\
    python scripts/etl/replay_dlq.py --max 1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

import httpx
import nats


STREAM = os.environ.get("INGEST_STREAM_NAME", "FRAUD_EVENTS")
SUBJECT_DLQ = os.environ.get("INGEST_DLQ_SUBJECT", "fraud.events.dlq")
DECISION_URL = os.environ.get("DECISION_API_URL", "http://localhost:8000").rstrip("/")


async def _run(max_msgs: int, dry_run: bool) -> None:
    nc = await nats.connect(os.environ.get("NATS_URL", "nats://localhost:4222"))
    js = nc.jetstream()
    sub = await js.pull_subscribe(
        f"{SUBJECT_DLQ}.>",
        durable="dlq-replay-cli",
        stream=STREAM,
    )
    http = httpx.AsyncClient(timeout=30.0)
    processed = 0
    try:
        while processed < max_msgs:
            try:
                msgs = await sub.fetch(batch=1, timeout=2)
            except nats.errors.TimeoutError:
                break
            for msg in msgs:
                processed += 1
                try:
                    env = json.loads(msg.data.decode())
                except json.JSONDecodeError:
                    print("skip: invalid json", file=sys.stderr)
                    await msg.term()
                    continue
                original = env.get("original")
                if not isinstance(original, dict):
                    print("skip: missing original", file=sys.stderr)
                    await msg.term()
                    continue
                if dry_run:
                    print(json.dumps({"dry_run": True, "reason": env.get("reason"), "keys": list(original.keys())}))
                    await msg.ack()
                    continue
                r = await http.post(f"{DECISION_URL}/v1/decisions/evaluate", json=original)
                if r.status_code < 400:
                    await msg.ack()
                    print("acked", original.get("tenant_id"), r.status_code)
                else:
                    print("evaluate failed", r.status_code, r.text[:200], file=sys.stderr)
                    await msg.nak(delay=30)
    finally:
        await http.aclose()
        await nc.drain()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--max", type=int, default=10)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    asyncio.run(_run(args.max, args.dry_run))


if __name__ == "__main__":
    main()
