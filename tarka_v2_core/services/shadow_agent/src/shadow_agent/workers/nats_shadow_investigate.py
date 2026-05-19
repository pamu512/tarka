"""
NATS consumer for ``shadow.investigate`` (orchestrator publishes on REVIEW).

Uses :func:`~shadow_agent.ai_gateway.factory.build_ai_gateway` so demo routes to Ollama with a
concurrency semaphore and cloud routes to vLLM / LB without a global lock.

Run (requires ``tarka-orchestrator[worker]`` / ``nats-py``)::

    NATS_URL=nats://127.0.0.1:4222 \\
      python -m shadow_agent.workers.nats_shadow_investigate
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal

logger = logging.getLogger(__name__)


async def run() -> None:
    from shadow_agent.ai_gateway.factory import build_ai_gateway

    nats_url = (os.environ.get("NATS_URL") or "").strip()
    if not nats_url:
        raise RuntimeError("NATS_URL is required")

    import nats  # noqa: PLC0415

    gateway = build_ai_gateway()
    subject = (os.environ.get("SHADOW_DISPATCH_NATS_SUBJECT") or "shadow.investigate").strip()
    nc = await nats.connect(nats_url)

    async def _on(msg: object) -> None:
        try:
            payload = json.loads(msg.data.decode()) if getattr(msg, "data", None) else {}
        except Exception:
            payload = {}
        logger.info("shadow_investigate_recv subject=%s keys=%s", subject, list(payload.keys()))

        async def _noop() -> None:
            return None

        await gateway.run_shadow_investigate_inference(_noop)

    await nc.subscribe(subject, cb=_on)
    logger.info(
        "nats_shadow_investigate_subscribed subject=%s gateway=%s", subject, type(gateway).__name__
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
