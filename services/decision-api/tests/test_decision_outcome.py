"""DecisionOutcomeHandler scheduling and fail-closed helpers."""

from decision_api.decision_outcome import (
    DecisionOutcomeContext,
    force_deny_from_degrade_tags,
    schedule_decision_outcomes,
    try_record_evaluate_decision_graph,
    wrap_outcome_task,
)
from decision_api.degraded_decision_metrics import record_degraded_decision_metrics
from decision_api.evaluate.score import signal_availability_notes_from_tags


class _Bg:
    def __init__(self) -> None:
        self.tasks: list[tuple] = []

    def add_task(self, fn, *args, **kwargs):
        self.tasks.append((fn, args, kwargs))


def test_try_record_evaluate_decision_graph_failsoft(monkeypatch):
    import tarka_shared.decision_graph_client as client

    ctx = DecisionOutcomeContext(
        trace_id="tr",
        tenant_id="ten",
        entity_id="e",
        event_type="login",
        decision="review",
        score=70.0,
        tags=[],
        device_context={"device_id": "dev-1"},
    )
    monkeypatch.setattr(client, "graph_write_url_configured", lambda: False)
    assert try_record_evaluate_decision_graph(ctx) is True
    monkeypatch.setattr(client, "graph_write_url_configured", lambda: True)
    monkeypatch.setattr(client, "record_decision_failsoft", lambda _p: None)
    assert try_record_evaluate_decision_graph(ctx) is False
    monkeypatch.setattr(client, "record_decision_failsoft", lambda _p: "dec_1")
    assert try_record_evaluate_decision_graph(ctx) is True
    ctx.shadow_request = True
    monkeypatch.setattr(client, "record_decision_failsoft", lambda _p: None)
    assert try_record_evaluate_decision_graph(ctx) is True


def test_graph_write_failed_signal_note():
    notes = signal_availability_notes_from_tags(["graph:write_failed"])
    assert notes and "still decided" in notes[0].lower()


def test_force_deny_from_catalog_and_graph_tags():
    assert force_deny_from_degrade_tags(["feature:catalog_fail_closed"])
    assert force_deny_from_degrade_tags(["graph:stale_fail_closed"])
    assert not force_deny_from_degrade_tags(["graph:unavailable"])
    assert not force_deny_from_degrade_tags(["graph:unconfigured"])


def test_schedule_decision_outcomes_enqueues_core_tasks():
    bg = _Bg()
    seen: list[str] = []

    async def _noop(*_a, **_k):
        return None

    schedule_decision_outcomes(
        bg,
        ctx=DecisionOutcomeContext(
            trace_id="t",
            tenant_id="ten",
            entity_id="e",
            event_type="login",
            decision="review",
            score=70.0,
            tags=["x"],
            decision_log_record={"trace_id": "t"},
            degrade_tags=["load_shedding:active", "feature:missing_amount"],
        ),
        http=object(),
        app_state=object(),
        emit_decision_log=_noop,
        maybe_dispatch_challenge_webhook=_noop,
        broadcast_decision=_noop,
        publish_decision=_noop,
        metrics_inc=lambda name, **_k: seen.append(name),
        case_create_on_deny_review=True,
        case_api_url="http://case.test",
    )
    assert any(getattr(t[0], "__name__", "") == "_noop" for t in bg.tasks)
    assert "fraud_decisions_review_total" in seen
    assert "tarka_degraded_decision_total" in seen
    assert "tarka_degraded_decision_load_shed_total" in seen
    assert "tarka_degraded_decision_missing_feature_total" in seen
    # case create enqueued for review
    assert any("maybe_create_case" in getattr(t[0], "__name__", "") for t in bg.tasks)


def test_allow_does_not_create_case():
    """ALLOW evaluations must never open a case."""
    bg = _Bg()

    async def _noop(*_a, **_k):
        return None

    schedule_decision_outcomes(
        bg,
        ctx=DecisionOutcomeContext(
            trace_id="t2",
            tenant_id="ten",
            entity_id="e2",
            event_type="payment",
            decision="allow",
            score=10.0,
            tags=[],
        ),
        http=object(),
        app_state=object(),
        emit_decision_log=_noop,
        maybe_dispatch_challenge_webhook=_noop,
        broadcast_decision=_noop,
        publish_decision=_noop,
        metrics_inc=lambda name, **_k: None,
        case_create_on_deny_review=True,
        case_api_url="http://case.test",
    )
    assert not any(
        "maybe_create_case" in getattr(t[0], "__name__", "") for t in bg.tasks
    )


def test_flag_does_not_create_case():
    """flag is residual signal — it must never mint a leftover."""
    bg = _Bg()

    async def _noop(*_a, **_k):
        return None

    schedule_decision_outcomes(
        bg,
        ctx=DecisionOutcomeContext(
            trace_id="t-flag",
            tenant_id="ten",
            entity_id="e-flag",
            event_type="payment",
            decision="flag",
            score=40.0,
            tags=[],
        ),
        http=object(),
        app_state=object(),
        emit_decision_log=_noop,
        maybe_dispatch_challenge_webhook=_noop,
        broadcast_decision=_noop,
        publish_decision=_noop,
        metrics_inc=lambda name, **_k: None,
        case_create_on_deny_review=True,
        case_api_url="http://case.test",
    )
    assert not any(
        "maybe_create_case" in getattr(t[0], "__name__", "") for t in bg.tasks
    )


def test_maybe_create_case_sends_origin_evaluate_and_last_outcome():
    import asyncio
    from types import SimpleNamespace

    from decision_api.decision_outcome import maybe_create_case_for_outcome

    captured: dict = {}

    class _Http:
        async def post(self, url, *, json=None, headers=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            return SimpleNamespace(status_code=201)

    ctx = DecisionOutcomeContext(
        trace_id="tr-deny",
        tenant_id="ten",
        entity_id="e1",
        event_type="payment",
        decision="deny",
        score=90.0,
        tags=[],
    )
    asyncio.run(
        maybe_create_case_for_outcome(
            http=_Http(),
            case_api_url="http://case.test",
            ctx=ctx,
            headers={},
        )
    )
    assert captured["json"]["labels"] == ["origin:evaluate"]
    assert captured["json"]["last_outcome"] == "deny"


def test_case_create_uses_internal_token_header():
    """When case_internal_token is set, the enqueued case create task passes X-Internal-Token."""
    import asyncio
    from types import SimpleNamespace

    bg = _Bg()
    captured_headers: list[dict] = []

    async def _noop(*_a, **_k):
        return None

    class _FakeHttp:
        async def post(self, url, *, json=None, headers=None, timeout=None):
            captured_headers.append(dict(headers or {}))
            return SimpleNamespace(status_code=201)

    schedule_decision_outcomes(
        bg,
        ctx=DecisionOutcomeContext(
            trace_id="t3",
            tenant_id="ten",
            entity_id="e3",
            event_type="payment",
            decision="deny",
            score=95.0,
            tags=["high_risk"],
        ),
        http=_FakeHttp(),
        app_state=object(),
        emit_decision_log=_noop,
        maybe_dispatch_challenge_webhook=_noop,
        broadcast_decision=_noop,
        publish_decision=_noop,
        metrics_inc=lambda name, **_k: None,
        case_create_on_deny_review=True,
        case_api_url="http://case.test",
        case_internal_token="s2s-secret-token",
    )
    case_tasks = [
        t for t in bg.tasks if "maybe_create_case" in getattr(t[0], "__name__", "")
    ]
    assert len(case_tasks) == 1
    fn, args, kwargs = case_tasks[0]
    asyncio.run(fn(*args, **kwargs))
    assert len(captured_headers) == 1
    assert captured_headers[0].get("X-Internal-Token") == "s2s-secret-token"


def test_degraded_metrics_dedupes_reason():
    seen: list[str] = []
    emitted = record_degraded_decision_metrics(
        ["feature:missing_amount", "feature:missing_device_fingerprint"],
        metrics_inc=lambda name, **_k: seen.append(name),
    )
    assert emitted == ["missing_feature"]
    assert seen.count("tarka_degraded_decision_missing_feature_total") == 1


def test_wrap_outcome_task_failure_increments_metric():
    import asyncio

    seen: list[str] = []

    async def _boom():
        raise RuntimeError("side-effect failed")

    wrapped = wrap_outcome_task(_boom, lambda name, **_k: seen.append(name))
    asyncio.run(wrapped())
    assert any("decision_outcome_failed" in n and "_boom" in n for n in seen)
