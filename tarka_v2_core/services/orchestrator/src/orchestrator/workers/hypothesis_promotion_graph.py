"""
NATS consumer: promoted shadow rules → JanusGraph ``high_risk`` hardening (Prompt 200).

Run (requires ``tarka-orchestrator[janus,worker]``)::

    NATS_URL=nats://127.0.0.1:4222 GRAPH_BACKEND=janusgraph GREMLIN_REMOTE_URL=ws://127.0.0.1:8182/gremlin \\
      python -m orchestrator.workers.hypothesis_promotion_graph
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal

logger = logging.getLogger(__name__)


def _promotion_subject() -> str:
    return (os.environ.get("HYPOTHESIS_PROMOTION_NATS_SUBJECT") or "tarka.hypothesis.promoted").strip()


def _promotion_queue() -> str:
    return (os.environ.get("HYPOTHESIS_PROMOTION_GRAPH_QUEUE") or "hypothesis-promotion-graph").strip()


async def handle_promotion_message(payload: dict, *, graph_client: object | None = None) -> dict:
    from orchestrator.graph.client import JanusGraphClient
    from orchestrator.graph.promotion_hardening import apply_promotion_hardening_to_graph

    if payload.get("event") != "rule_promoted_to_production":
        return {"ok": False, "reason": "unknown_event"}

    client: object | None
    if graph_client is not None:
        client = graph_client
    else:
        backend = (os.environ.get("GRAPH_BACKEND") or "").strip().lower()
        client = JanusGraphClient.try_from_env() if backend == "janusgraph" else None

    return await apply_promotion_hardening_to_graph(client, payload)


async def run() -> None:
    nats_url = (os.environ.get("NATS_URL") or "").strip()
    if not nats_url:
        raise RuntimeError("NATS_URL is required")

    import nats  # noqa: PLC0415

    subject = _promotion_subject()
    queue = _promotion_queue()
    nc = await nats.connect(nats_url)

    async def _on(msg: object) -> None:
        try:
            payload = json.loads(msg.data.decode()) if getattr(msg, "data", None) else {}
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            out = await handle_promotion_message(payload)
            logger.info("hypothesis_promotion_graph_handled %s", out)
        except Exception:
            logger.exception("hypothesis_promotion_graph_handler_failed")

    await nc.subscribe(subject, queue=queue, cb=_on)
    logger.info(
        "hypothesis_promotion_graph_subscribed subject=%s queue=%s",
        subject,
        queue,
    )

    stop = asyncio.Event()

    def _stop() -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass

    await stop.wait()
    await nc.drain()
    await nc.close()


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    asyncio.run(run())


if __name__ == "__main__":
    main()
