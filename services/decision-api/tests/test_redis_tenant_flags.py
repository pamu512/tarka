"""Redis tenant flags get/patch."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from decision_api.redis_store import RedisTags


@pytest.mark.asyncio
async def test_get_set_tenant_flags():
    r = RedisTags("redis://fake")
    store: dict[str, str] = {}

    async def fake_get(key: str):
        return store.get(key)

    async def fake_set(key: str, val: str):
        store[key] = val
        return True

    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=fake_get)
    mock_client.set = AsyncMock(side_effect=fake_set)
    r._client = mock_client

    assert await r.get_tenant_flags("t1") == {}
    await r.set_tenant_flags("t1", {"disable_ml": True})
    assert await r.get_tenant_flags("t1") == {"disable_ml": True}
    merged = await r.patch_tenant_flags("t1", {"disable_opa": True, "disable_ml": None})
    assert merged.get("disable_opa") is True
    assert "disable_ml" not in merged
