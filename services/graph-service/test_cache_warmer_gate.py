"""Gate: after a user block, linked ``device_id`` (device hash) appears under ``proximity_risk:{id}`` in Redis."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import cache_warmer  # noqa: E402


def _gremlin_chain_mock(element_maps: list[dict]) -> MagicMock:
    """Return a ``g`` mock with ``V().has().both().dedup().elementMap().toList()``."""
    leaf = MagicMock()
    leaf.toList.return_value = element_maps
    d = MagicMock()
    d.elementMap.return_value = leaf
    c = MagicMock()
    c.dedup.return_value = d
    b = MagicMock()
    b.both.return_value = c
    h = MagicMock()
    h.has.return_value = b
    root = MagicMock()
    root.V.return_value = h
    return root


@pytest.mark.anyio
async def test_block_user_warms_linked_device_hash_in_redis() -> None:
    """Simulate JanusGraph returning a 1-hop ``Device`` neighbor; Redis must get ``proximity_risk:{device_id}``."""
    pytest.importorskip("gremlin_python")
    from gremlin_python.process.traversal import T

    fakeredis = pytest.importorskip("fakeredis")
    from fakeredis import FakeAsyncRedis

    device_hash = "canvas_or_device_hash_gate_100"
    blocked_user = "user-blocked-100"
    ems = [
        {
            T.label: cache_warmer.LABEL_DEVICE,
            "device_id": device_hash,
            "tenant_id": "t-demo",
        },
    ]
    g = _gremlin_chain_mock(ems)
    redis = FakeAsyncRedis(decode_responses=True)

    warmed = await cache_warmer.warm_proximity_cache_for_blocked_user(
        redis,
        g,
        blocked_user_id=blocked_user,
        ttl_seconds=3600,
    )

    assert device_hash in warmed
    key = cache_warmer.proximity_risk_key(device_hash)
    assert await redis.get(key) == "1"


def test_element_map_device_id_roundtrip() -> None:
    pytest.importorskip("gremlin_python")
    from gremlin_python.process.traversal import T

    em = {T.label: "Device", "device_id": "dh1", "tenant_id": "t"}
    assert cache_warmer.neighbor_external_id_from_element_map(em) == "dh1"
