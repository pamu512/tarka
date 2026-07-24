"""Unit tests for EntityLinkStore with AsyncMock Redis."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from decision_api.entity_link_store import LINK_VENDOR_PREFIX, EntityLinkStore


@pytest.mark.asyncio
async def test_record_vendor_bridge_setex():
    store = EntityLinkStore()
    client = MagicMock()
    pipe = MagicMock()
    pipe.setex = MagicMock(return_value=pipe)
    client.pipeline = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=True)
    store.set_client(client)

    await store.record_vendor_bridge(
        "t1",
        "user-9",
        {"vendor_visitor_id": "vis-x", "other": 1},
    )

    expected_key = f"{LINK_VENDOR_PREFIX}t1:visitor:vis-x"
    pipe.setex.assert_called_once()
    assert pipe.setex.call_args[0][0] == expected_key
    client.pipeline.assert_called_once()


@pytest.mark.asyncio
async def test_get_entities_for_device_zrevrange():
    store = EntityLinkStore()
    client = MagicMock()
    client.zrevrange = AsyncMock(return_value=["a", "b"])
    store.set_client(client)

    out = await store.get_entities_for_device("t", "dev1", limit=5)
    assert out == ["a", "b"]
    client.zrevrange.assert_called_once()
