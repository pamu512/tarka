"""Graph entity-risk freshness guard and event_type policy."""

from datetime import UTC, datetime, timedelta

from decision_api.graph_risk_freshness import (
    evaluate_graph_risk_freshness,
    parse_freshness_policy_by_event,
    warn_if_graph_risk_stale,
)


def test_stale_graph_risk_warns_and_metrics():
    seen: list[str] = []

    def inc(name: str) -> None:
        seen.append(name)

    old = (datetime.now(UTC) - timedelta(minutes=45)).isoformat().replace("+00:00", "Z")
    age = warn_if_graph_risk_stale(
        {
            "graph_data_as_of": old,
            "graph_checkpoint": "standard",
        },
        max_age_minutes=30,
        tenant_id="t1",
        entity_id="e1",
        metrics_inc=inc,
    )
    assert age is not None
    assert age > 30
    assert seen == ["tarka_graph_risk_stale_total"]


def test_fresh_graph_risk_silent():
    seen: list[str] = []
    recent = (
        (datetime.now(UTC) - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    )
    age = warn_if_graph_risk_stale(
        {"graph_data_as_of": recent},
        max_age_minutes=30,
        tenant_id="t1",
        entity_id="e1",
        metrics_inc=seen.append,
    )
    assert age is None
    assert seen == []


def test_disabled_when_max_age_zero():
    old = (datetime.now(UTC) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    assert (
        warn_if_graph_risk_stale(
            {"graph_data_as_of": old},
            max_age_minutes=0,
            tenant_id="t1",
            entity_id="e1",
            metrics_inc=lambda _: None,
        )
        is None
    )


def test_missing_graph_data_as_of_skips():
    assert (
        warn_if_graph_risk_stale(
            {"graph_checkpoint": "minimal"},
            max_age_minutes=30,
            tenant_id="t1",
            entity_id="e1",
            metrics_inc=lambda _: None,
        )
        is None
    )


def test_parse_policy_by_event():
    assert parse_freshness_policy_by_event("payment:fail_closed,login:skip") == {
        "payment": "fail_closed",
        "login": "skip",
    }


def test_stale_fail_closed_for_payment():
    old = (datetime.now(UTC) - timedelta(minutes=60)).isoformat().replace("+00:00", "Z")
    result = evaluate_graph_risk_freshness(
        {"graph_data_as_of": old},
        max_age_minutes=30,
        tenant_id="t1",
        entity_id="e1",
        event_type="payment",
        default_policy="warn",
        policy_by_event_type={"payment": "fail_closed"},
    )
    assert result.action == "fail_closed"


def test_stale_skip_for_login():
    old = (datetime.now(UTC) - timedelta(minutes=60)).isoformat().replace("+00:00", "Z")
    result = evaluate_graph_risk_freshness(
        {"graph_data_as_of": old},
        max_age_minutes=30,
        tenant_id="t1",
        entity_id="e1",
        event_type="login",
        default_policy="warn",
        policy_by_event_type={"login": "skip"},
    )
    assert result.action == "skip"
