"""G4.1: outbound enforcement webhooks are HMAC-signed; mock consumer verifies."""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
from pathlib import Path

import pytest

from decision_api.enforcement import apply_enforcement_adapters

_REPO = Path(__file__).resolve().parents[3]
_MOCK = _REPO / "scripts" / "oss" / "enforcement_webhook_mock.py"


def _mock_verify():
    spec = importlib.util.spec_from_file_location("enforcement_webhook_mock", _MOCK)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._verify


@pytest.mark.asyncio
async def test_outbound_webhook_signature_verified_by_mock(monkeypatch, tmp_path) -> None:
    secret = "g41-webhook-secret"
    monkeypatch.setenv("TARKA_ENFORCEMENT_WEBHOOK_URL", "http://hooks.test/enforcement")
    monkeypatch.setenv("TARKA_ENFORCEMENT_WEBHOOK_SECRET", secret)
    monkeypatch.setenv(
        "TARKA_ENFORCEMENT_JOURNAL_PATH", str(tmp_path / "enforcement_delivery.jsonl")
    )
    posts: list[dict] = []

    class _Resp:
        status_code = 204

    class _Http:
        async def post(self, url, content=None, headers=None, timeout=None):
            posts.append(
                {"url": url, "content": content, "headers": dict(headers or {})}
            )
            return _Resp()

    out = await apply_enforcement_adapters(
        http=_Http(),
        trace_id="tr-sig",
        tenant_id="t1",
        entity_id="e1",
        event_type="payment",
        decision="deny",
        score=88.0,
        tags=["x"],
    )
    assert out["webhook"]["ok"] is True
    assert posts, "enforcement webhook must POST when URL is set"
    raw = posts[0]["content"]
    headers = posts[0]["headers"]
    sig = headers.get("x-tarka-signature") or headers.get("X-Tarka-Signature")
    assert sig, "signed outbound requires x-tarka-signature"
    expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    assert sig == expected
    verify = _mock_verify()
    assert verify(raw, secret, sig) is True
    assert verify(raw, "wrong-secret", sig) is False
    assert verify(raw, secret, None) is False
    body = json.loads(raw.decode("utf-8"))
    assert body["suggested_actions"] == ["deny"]
    assert body["action_ids"]["deny"] == body["action_id"]
    assert len(body["action_id"]) == 64
