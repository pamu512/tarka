"""Platform enforcement adapters (Wave D)."""

import pytest

from decision_api.decision_outcome import (
    DecisionOutcomeContext,
    schedule_decision_outcomes,
)
from decision_api.enforcement import (
    ENFORCEMENT_SCHEMA,
    apply_enforcement_adapters,
    resolve_enforcement_action,
)


@pytest.mark.parametrize(
    ("decision", "recommended", "expected"),
    [
        ("deny", None, "block"),
        ("deny", "allow", "block"),
        ("allow", None, "allow"),
        ("review", None, "allow"),
        ("review", "step_up_mfa", "step_up"),
        ("allow", "challenge", "step_up"),
        ("allow", "step-up-attestation", "step_up"),
    ],
)
def test_resolve_enforcement_action(
    decision: str, recommended: str | None, expected: str
) -> None:
    assert resolve_enforcement_action(decision, recommended) == expected


@pytest.mark.asyncio
async def test_apply_enforcement_metrics_without_webhook(monkeypatch) -> None:
    monkeypatch.delenv("TARKA_ENFORCEMENT_WEBHOOK_URL", raising=False)
    seen: list[str] = []

    class _Http:
        async def post(self, *_a, **_k):
            raise AssertionError("webhook must not fire when URL unset")

    out = await apply_enforcement_adapters(
        http=_Http(),
        trace_id="tr",
        tenant_id="t1",
        entity_id="e1",
        event_type="payment",
        decision="deny",
        score=99.0,
        tags=["x"],
        metrics_inc=seen.append,
    )
    assert out["enforcement_action"] == "block"
    assert out["webhook"] is None
    assert "tarka_enforcement_block_total" in seen
    assert "tarka_enforcement_total" in seen


@pytest.mark.asyncio
async def test_apply_enforcement_webhook(monkeypatch) -> None:
    monkeypatch.setenv("TARKA_ENFORCEMENT_WEBHOOK_URL", "http://hooks.test/enf")
    monkeypatch.setenv("TARKA_ENFORCEMENT_WEBHOOK_SECRET", "sekrit")
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
        trace_id="tr",
        tenant_id="t1",
        entity_id="e1",
        event_type="login",
        decision="review",
        score=55.0,
        tags=[],
        recommended_action="step_up_mfa",
        challenge_metadata={"policy_id": "default_v1"},
        metrics_inc=lambda *_a, **_k: None,
    )
    assert out["enforcement_action"] == "step_up"
    assert out["webhook"]["ok"] is True
    assert posts[0]["url"] == "http://hooks.test/enf"
    assert posts[0]["headers"]["x-tarka-enforcement-event"] == "step_up"
    assert "x-tarka-signature" in posts[0]["headers"]
    import json

    body = json.loads(posts[0]["content"].decode("utf-8"))
    assert body["schema_id"] == ENFORCEMENT_SCHEMA
    assert body["enforcement_action"] == "step_up"


def test_schedule_enqueues_enforcement() -> None:
    class _Bg:
        def __init__(self) -> None:
            self.tasks: list[tuple] = []

        def add_task(self, fn, *args, **kwargs):
            self.tasks.append((fn, args, kwargs))

    async def _noop(*_a, **_k):
        return None

    bg = _Bg()
    schedule_decision_outcomes(
        bg,
        ctx=DecisionOutcomeContext(
            trace_id="t",
            tenant_id="ten",
            entity_id="e",
            event_type="payment",
            decision="deny",
            score=100.0,
            tags=["list:blacklist"],
            recommended_action=None,
        ),
        http=object(),
        app_state=object(),
        emit_decision_log=_noop,
        maybe_dispatch_challenge_webhook=_noop,
        broadcast_decision=_noop,
        publish_decision=_noop,
        metrics_inc=lambda *_a, **_k: None,
    )
    enf = [
        t
        for t in bg.tasks
        if getattr(t[0], "__name__", "") == "apply_enforcement_adapters"
    ]
    assert len(enf) == 1
    assert enf[0][2]["decision"] == "deny"
    publish_calls = [
        t
        for t in bg.tasks
        if t[0] is _noop and len(t[1]) == 2 and isinstance(t[1][1], dict)
    ]
    assert any(c[1][1].get("enforcement_action") == "block" for c in publish_calls)
