"""Live JetStream: DLQ subject must not be consumed by decision-worker.

Skip when NATS_URL is unset or the broker is down (unit CI without Docker).
"""

from __future__ import annotations

import json
import os

import pytest

NATS_URL = (os.environ.get("NATS_URL") or "").strip()


def _nats_up(url: str) -> bool:
    try:
        import nats  # noqa: PLC0415
    except ImportError:
        return False

    async def _ping() -> bool:
        try:
            nc = await nats.connect(url)
            await nc.close()
            return True
        except Exception:
            return False

    import asyncio

    return asyncio.run(_ping())


pytestmark = pytest.mark.skipif(
    not NATS_URL or not _nats_up(NATS_URL),
    reason="NATS_URL unset or broker down",
)


@pytest.mark.asyncio
async def test_dlq_publish_is_outside_consumer_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    import event_ingest.main as main_mod
    from event_ingest.main import _connect_nats, _park_evaluate_4xx

    monkeypatch.setattr(main_mod.settings, "nats_url", NATS_URL)
    monkeypatch.setattr(main_mod.settings, "subject_prefix", "fraud.events")
    monkeypatch.setattr(main_mod.settings, "ingest_dlq_subject", "fraud.dlq.evaluate")
    monkeypatch.setattr(main_mod.settings, "ingest_dlq_stream_name", "FRAUD_DLQ")
    monkeypatch.setattr(main_mod.settings, "ingest_dlq_publish_on_evaluate_4xx", True)
    monkeypatch.setattr(main_mod.settings, "stream_name", "FRAUD_EVENTS")

    nc, js = await _connect_nats()
    try:
        parked = await _park_evaluate_4xx(
            js,
            nats_subject="fraud.events.t1.login",
            raw_event={"tenant_id": "t1"},
            eval_body={"entity_id": "e1"},
            status_code=422,
            response_text="bad",
        )
        assert parked is True

        events = await js.pull_subscribe(
            "fraud.events.>",
            durable="qa-dlq-loop-events",
            stream="FRAUD_EVENTS",
        )
        try:
            leaked = await events.fetch(batch=8, timeout=1)
        except Exception:
            leaked = []
        for msg in leaked:
            body = json.loads(msg.data.decode())
            await msg.ack()
            assert body.get("kind") != "evaluate_4xx"

        dlq = await js.pull_subscribe(
            "fraud.dlq.evaluate",
            durable="qa-dlq-loop-dlq",
            stream="FRAUD_DLQ",
        )
        parked_msgs = await dlq.fetch(batch=1, timeout=2)
        assert len(parked_msgs) == 1
        env = json.loads(parked_msgs[0].data.decode())
        assert env["kind"] == "evaluate_4xx"
        await parked_msgs[0].ack()
    finally:
        await nc.drain()
