"""STRICT_CONSISTENCY + KV fallback locking for redis_store."""

import asyncio

import pytest

from decision_api.config import settings
from decision_api.redis_store import RedisTags
from tarka_core.cache import LocalDictCache


@pytest.fixture
async def kv_disk_tags(tmp_path, monkeypatch):
    monkeypatch.setenv("TARKA_KV_FALLBACK_LOCK_PATH", str(tmp_path / "kv.lock"))
    r = RedisTags("")
    await r.connect(kv_fallback=LocalDictCache())
    yield r
    await r.close()


@pytest.mark.asyncio
async def test_strict_merge_tags_raises_without_redis(kv_disk_tags, monkeypatch):
    monkeypatch.setattr(settings, "strict_consistency", True)
    with pytest.raises(ConnectionError, match="merge_tags"):
        await kv_disk_tags.merge_tags("tenant", "entity", ["tag:a"])


@pytest.mark.asyncio
async def test_strict_consume_nonce_raises_without_redis(kv_disk_tags, monkeypatch):
    monkeypatch.setattr(settings, "strict_consistency", True)
    with pytest.raises(ConnectionError, match="consume_nonce"):
        await kv_disk_tags.consume_nonce("abc")


@pytest.mark.asyncio
async def test_kv_fallback_merge_uses_union_under_file_lock(kv_disk_tags, monkeypatch):
    monkeypatch.setattr(settings, "strict_consistency", False)
    await kv_disk_tags.merge_tags("t", "e", ["x"])
    await kv_disk_tags.merge_tags("t", "e", ["y"])
    merged = await kv_disk_tags.get_tags("t", "e")
    assert sorted(merged) == ["x", "y"]


@pytest.mark.asyncio
async def test_kv_fallback_merge_concurrent(kv_disk_tags, monkeypatch):
    monkeypatch.setattr(settings, "strict_consistency", False)

    async def add(i: int) -> None:
        await kv_disk_tags.merge_tags("t", "e", [f"k{i}"])

    await asyncio.gather(*(add(i) for i in range(8)))
    merged = await kv_disk_tags.get_tags("t", "e")
    assert len(merged) == 8


@pytest.mark.asyncio
async def test_non_strict_merge_raises_when_no_backing_store(monkeypatch):
    monkeypatch.setattr(settings, "strict_consistency", False)
    r = RedisTags("")
    await r.connect()
    with pytest.raises(ConnectionError, match="merge_tags requires Redis"):
        await r.merge_tags("t", "e", ["only"])
