"""_graph_upsert writes Hunt objects, not a second session dialect."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from tarka_shared.decision_graph_payload import build_evaluate_objects


def test_graph_upsert_uses_evaluate_objects_not_custom_session():
    src = Path(__file__).resolve().parents[1] / "src" / "decision_api" / "main.py"
    text = src.read_text()
    start = text.index("async def _graph_upsert(")
    end = text.index("async def _graph_upsert_stepped(", start)
    body = text[start:end]
    assert "build_evaluate_objects" in body
    assert "attach_decision_object" in body
    assert "graph_writes_from_hints" in body
    assert "partner_graph_hints" in body
    assert 'entity_type": "Custom"' not in body
    assert '"relationship": "USED"' not in body


def test_evaluate_objects_session_is_typed():
    objects, links = build_evaluate_objects(
        trace_id="tr-1",
        entity_id="alice",
        event_type="login",
        payload={},
        device_context={"device_id": "dev-1"},
        session_id="sess-1",
    )
    types = {o["entity_type"]: o["external_id"] for o in objects}
    assert types["Session"] == "sess:sess-1"
    assert "Custom" not in types
    rels = {lk["relationship"] for lk in links}
    assert "USED_DEVICE" in rels
    assert "USED_SESSION" in rels
    assert "USED" not in rels


@pytest.mark.asyncio
async def test_graph_upsert_does_not_treat_rejected_link_as_success(monkeypatch):
    from decision_api.config import settings
    from decision_api.main import _graph_upsert
    from decision_api.schemas import EvaluateRequest

    monkeypatch.setattr(settings, "graph_service_url", "http://graph.test")

    class _Http:
        def __init__(self) -> None:
            self.posts: list[tuple[str, dict]] = []

        async def post(self, url, json=None, headers=None):
            self.posts.append((url, json))
            request = httpx.Request("POST", url)
            return httpx.Response(422, request=request, json={"detail": "unsigned etype"})

    body = EvaluateRequest(
        tenant_id="demo",
        event_type="payment",
        entity_id="fraud_frank",
        role="member",
        payload={"amount": 10, "currency": "USD", "counterparty_entity_id": "mule_ivan"},
    )
    with pytest.raises(httpx.HTTPStatusError):
        await _graph_upsert(_Http(), body, "tr-1", [], decision="allow")
