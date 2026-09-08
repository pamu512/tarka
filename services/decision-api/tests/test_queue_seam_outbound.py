"""W4 queue.upsert: empty URL off; signed POST when set; mint never waits."""

from __future__ import annotations

import json

import pytest

from decision_api.queue_seam import emit_queue_upsert, last_queue_status


@pytest.mark.asyncio
async def test_empty_url_no_post(monkeypatch) -> None:
    monkeypatch.delenv("QUEUE_WEBHOOK_URL", raising=False)

    class _Http:
        async def post(self, *_a, **_k):
            raise AssertionError("must not POST")

    out = await emit_queue_upsert(
        http=_Http(),
        tenant_id="t1",
        leftover_id="lo-1",
        trace_id="tr-1",
        entity_id="e1",
        action="deny",
    )
    assert out["dispatched"] is False
    assert last_queue_status()["connected"] is False


@pytest.mark.asyncio
async def test_url_posts_required_keys(monkeypatch) -> None:
    monkeypatch.setenv("QUEUE_WEBHOOK_URL", "http://hooks.test/queue")
    monkeypatch.setenv("QUEUE_WEBHOOK_SECRET", "sekrit")
    posts: list[dict] = []

    class _Resp:
        status_code = 201

    class _Http:
        async def post(self, url, content=None, headers=None, timeout=None):
            posts.append(
                {"url": url, "content": content, "headers": dict(headers or {})}
            )
            return _Resp()

    out = await emit_queue_upsert(
        http=_Http(),
        tenant_id="t1",
        leftover_id="lo-1",
        trace_id="tr-1",
        entity_id="e1",
        action="review",
        pack_why_summary="hit:seed",
        evaluation_token="tr-1",
    )
    assert out["ok"] is True
    body = json.loads(posts[0]["content"].decode("utf-8"))
    for key in (
        "schema_id",
        "tenant_id",
        "leftover_id",
        "trace_id",
        "evaluation_token",
        "entity_id",
        "action",
        "emitted_at",
    ):
        assert body[key]
    assert posts[0]["headers"]["x-tarka-signature"]
    assert last_queue_status()["connected"] is True


@pytest.mark.asyncio
async def test_webhook_down_does_not_raise(monkeypatch) -> None:
    monkeypatch.setenv("QUEUE_WEBHOOK_URL", "http://hooks.test/queue")

    class _Http:
        async def post(self, *_a, **_k):
            raise RuntimeError("down")

    out = await emit_queue_upsert(
        http=_Http(),
        tenant_id="t1",
        leftover_id="lo-1",
        trace_id="tr-1",
        entity_id="e1",
        action="deny",
    )
    assert out["ok"] is False
    assert "error" in out
