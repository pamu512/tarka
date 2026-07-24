"""tarka_core messaging/cache primitives used by Tarka Micro."""

from __future__ import annotations

import asyncio
import json

import pytest

from tarka_core.cache import LocalDictCache
from tarka_core.messaging import LocalAsyncBroker, PublishDelivery


@pytest.mark.asyncio
async def test_local_dict_cache_isolation_on_get() -> None:
    c = LocalDictCache()
    inner = {"a": [1, 2]}
    await c.set("k", json.dumps(inner))
    inner["a"].append(99)
    raw = await c.get("k")
    assert raw is not None
    assert json.loads(raw)["a"] == [1, 2]


@pytest.mark.asyncio
async def test_local_async_broker_dead_letters_on_handler_failure() -> None:
    b = LocalAsyncBroker(num_workers=1)

    async def _boom(_subject: str, _payload: bytes) -> None:
        raise RuntimeError("handler failed")

    await b.start()
    await b.subscribe("fraud.test", _boom)
    await b.publish("fraud.test", b"x", delivery=PublishDelivery.CORE)
    await asyncio.sleep(0.35)
    dl = await b.drain_dead_letters()
    await b.aclose()
    assert len(dl) >= 1
    assert dl[0].subject == "fraud.test"
    assert "handler failed" in dl[0].error
