#!/usr/bin/env python3
"""
Pull messages from the ingest DLQ JetStream subject and optionally re-post to evaluate.

Requires: nats-py, running NATS with a stream covering the DLQ subject (e.g. fraud.events.>).

  python scripts/etl/replay_dlq.py --nats-url nats://localhost:4222 --subject fraud.events.dlq --max 5 --dry-run
  DECISION_API_URL=http://localhost:8000 python scripts/etl/replay_dlq.py --max 1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]


async def _run(
    *,
    nats_url: str,
    subject: str,
    stream_name: str,
    durable: str,
    max_msgs: int,
    dry_run: bool,
    decision_url: str,
) -> int:
    try:
        import nats  # type: ignore[import-untyped]
    except ImportError:
        print("Install nats-py: pip install nats-py", file=sys.stderr)
        return 2

    nc = await nats.connect(nats_url)
    js = nc.jetstream()
    sub = await js.pull_subscribe(subject, durable=durable, stream=stream_name)

    import httpx

    processed = 0
    try:
        while processed < max_msgs:
            try:
                msgs = await sub.fetch(batch=min(32, max_msgs - processed), timeout=2.0)
            except Exception:
                break
            if not msgs:
                break
            for msg in msgs:
                processed += 1
                try:
                    data = json.loads(msg.data.decode())
                except json.JSONDecodeError:
                    print(f"skip: invalid JSON seq={getattr(msg.metadata, 'sequence', '?')}", file=sys.stderr)
                    await msg.ack()
                    continue

                inner = data.get("evaluate_request")
                if not isinstance(inner, dict):
                    inner = data.get("event")
                if not isinstance(inner, dict):
                    print("skip: no evaluate_request/event", file=sys.stderr)
                    await msg.ack()
                    continue

                # Strip ingest-only keys for evaluate
                body = {k: v for k, v in inner.items() if k != "_ingest_id"}

                if dry_run:
                    print(json.dumps({"dry_run": True, "would_post": body}, default=str)[:2000])
                else:
                    async with httpx.AsyncClient(timeout=30.0) as http:
                        r = await http.post(f"{decision_url.rstrip('/')}/v1/decisions/evaluate", json=body)
                    print(f"evaluate {r.status_code} seq={getattr(msg.metadata, 'sequence', '?')}")
                await msg.ack()

                if processed >= max_msgs:
                    break
    finally:
        await nc.drain()

    print(f"Processed {processed} message(s).")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Replay DLQ messages to Decision API evaluate.")
    p.add_argument("--nats-url", default=os.environ.get("NATS_URL", "nats://localhost:4222"))
    p.add_argument("--subject", default=os.environ.get("INGEST_DLQ_SUBJECT", "fraud.events.dlq"))
    p.add_argument("--stream", default=os.environ.get("INGEST_STREAM_NAME", "FRAUD_EVENTS"))
    p.add_argument("--durable", default="dlq-replay-cli")
    p.add_argument("--max", type=int, default=10)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--decision-api-url",
        default=os.environ.get("DECISION_API_URL", "http://localhost:8000"),
    )
    args = p.parse_args(argv)

    return asyncio.run(
        _run(
            nats_url=args.nats_url,
            subject=args.subject,
            stream_name=args.stream,
            durable=args.durable,
            max_msgs=max(1, args.max),
            dry_run=args.dry_run,
            decision_url=args.decision_api_url,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
