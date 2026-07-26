"""DecisionOutcomeHandler scheduling and fail-closed helpers."""

from decision_api.decision_outcome import (
    DecisionOutcomeContext,
    force_deny_from_degrade_tags,
    schedule_decision_outcomes,
)
from decision_api.degraded_decision_metrics import record_degraded_decision_metrics


class _Bg:
    def __init__(self) -> None:
        self.tasks: list[tuple] = []

    def add_task(self, fn, *args, **kwargs):
        self.tasks.append((fn, args, kwargs))


def test_force_deny_from_catalog_and_graph_tags():
    assert force_deny_from_degrade_tags(["feature:catalog_fail_closed"])
    assert force_deny_from_degrade_tags(["graph:stale_fail_closed"])
    assert not force_deny_from_degrade_tags(["graph:unavailable"])


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
    assert any(t[0] is _noop for t in bg.tasks)
    assert "fraud_decisions_review_total" in seen
    assert "tarka_degraded_decision_total" in seen
    assert "tarka_degraded_decision_load_shed_total" in seen
    assert "tarka_degraded_decision_missing_feature_total" in seen
    # case create enqueued for review
    assert any("maybe_create_case" in getattr(t[0], "__name__", "") for t in bg.tasks)


def test_degraded_metrics_dedupes_reason():
    seen: list[str] = []
    emitted = record_degraded_decision_metrics(
        ["feature:missing_amount", "feature:missing_device_fingerprint"],
        metrics_inc=lambda name, **_k: seen.append(name),
    )
    assert emitted == ["missing_feature"]
    assert seen.count("tarka_degraded_decision_missing_feature_total") == 1
