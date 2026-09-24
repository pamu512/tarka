"""Concurrent first-link race: AGE edge-label DDL (DuplicateTableError).

When parallel writers send the first links for a relationship label, AGE
creates the label's backing table lazily and the DDL races — one writer wins,
the others see DuplicateTableError and (pre-fix) 502. Contract: the loser
retries the create once and succeeds.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import asyncpg
import pytest

from graph_service import age_client


@pytest.mark.asyncio
async def test_create_link_retries_on_duplicate_table(monkeypatch):
    calls = {"n": 0}

    class FakeConn:
        async def fetchrow(self, q, *a):
            if "labels(a)" in q:
                # typed-edge metadata check passes (untyped rels)
                return {"la": '["Person"]', "lb": '["Device"]'}
            # q_exist: no existing edge
            return {"gid": None}

        async def execute(self, q, *a):
            calls["n"] += 1
            if calls["n"] == 1:
                raise asyncpg.exceptions.DuplicateTableError(
                    'relation "USED_DEVICE" already exists'
                )
            return "OK"

    class FakeCtx:
        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(age_client, "_acquire", lambda: FakeCtx())
    monkeypatch.setattr(
        age_client,
        "get_pool",
        AsyncMock(return_value=object()),
    )
    monkeypatch.setattr(
        age_client,
        "get_allowed_rels",
        lambda tenant_id: {"USED_DEVICE"},
    )
    monkeypatch.setattr(
        age_client,
        "require_etype",
        lambda tenant_id, rel: rel,
    )

    await age_client.create_link(
        "t-race", "p-1", "d-1", "USED_DEVICE", {"trace_id": "tr"}
    )
    assert calls["n"] == 2, "create must retry exactly once after DuplicateTableError"
