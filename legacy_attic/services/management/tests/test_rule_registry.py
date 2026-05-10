"""RuleRegistry temporal semantics and immutability."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tarka_management import Base, DuplicateRuleVersionError, RuleRegistry

UTC = timezone.utc


def _utc(dt: datetime) -> datetime:
    """SQLite returns naive datetimes from ``TIMESTAMP``; normalize for assertions."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False, future=True)


def test_publish_then_get_active(session_factory):
    reg = RuleRegistry()
    t0 = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    body_v1 = '{"kind":"compare_leaf","id":"x","path":"/a","op":"eq","expected":1}'
    with session_factory() as session:
        v1 = reg.publish_new_version(session, "fraud.login", body_v1, effective_at=t0)
        session.commit()
        assert v1.content_hash == reg.content_hash(body_v1)
        assert v1.valid_to is None

    with session_factory() as session:
        active = reg.get_active_version(session, "fraud.login", t0 + timedelta(seconds=1))
        assert active is not None
        assert active.rule_body == body_v1
        assert _utc(active.valid_from) == t0


def test_second_version_closes_prior_forensic_replay(session_factory):
    reg = RuleRegistry()
    t1 = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)
    t2 = datetime(2025, 7, 1, 0, 0, 0, tzinfo=UTC)
    mid = datetime(2025, 6, 15, 0, 0, 0, tzinfo=UTC)
    b1 = '{"kind":"compare_leaf","id":"a","path":"/x","op":"eq","expected":1}'
    b2 = '{"kind":"compare_leaf","id":"a","path":"/x","op":"eq","expected":2}'

    with session_factory() as session:
        reg.publish_new_version(session, "rule-a", b1, effective_at=t1)
        session.commit()

    with session_factory() as session:
        reg.publish_new_version(session, "rule-a", b2, effective_at=t2)
        session.commit()

    with session_factory() as session:
        assert reg.get_active_version(session, "rule-a", t1).rule_body == b1
        assert reg.get_active_version(session, "rule-a", mid).rule_body == b1
        assert reg.get_active_version(session, "rule-a", t2).rule_body == b2
        assert reg.get_active_version(session, "rule-a", t2 + timedelta(hours=1)).rule_body == b2


def test_duplicate_content_rejected(session_factory):
    reg = RuleRegistry()
    t = datetime(2025, 1, 2, tzinfo=UTC)
    body = '{"kind":"compare_leaf","id":"z","path":"/p","op":"eq","expected":true}'
    with session_factory() as session:
        reg.publish_new_version(session, "r1", body, effective_at=t)
        session.commit()

    with session_factory() as session:
        with pytest.raises(DuplicateRuleVersionError):
            reg.publish_new_version(session, "r1", body, effective_at=t + timedelta(days=1))
        session.rollback()


def test_same_body_different_rule_names_allowed(session_factory):
    reg = RuleRegistry()
    t = datetime(2025, 3, 1, tzinfo=UTC)
    body = '{"kind":"compare_leaf","id":"z","path":"/p","op":"eq","expected":3}'
    with session_factory() as session:
        reg.publish_new_version(session, "tenant_a.rule", body, effective_at=t)
        reg.publish_new_version(session, "tenant_b.rule", body, effective_at=t)
        session.commit()


def test_naive_timestamp_rejected(session_factory):
    reg = RuleRegistry()
    with session_factory() as session:
        with pytest.raises(ValueError, match="timezone-aware"):
            reg.get_active_version(session, "x", datetime.now())


def test_boundary_half_open_interval(session_factory):
    """At exact ``valid_to`` of v1, v2 is active (valid_to is exclusive end)."""
    reg = RuleRegistry()
    t_switch = datetime(2025, 8, 8, 15, 30, 0, tzinfo=UTC)
    b1 = '{"v":1}'
    b2 = '{"v":2}'
    with session_factory() as session:
        reg.publish_new_version(session, "edge", b1, effective_at=t_switch - timedelta(days=30))
        session.commit()
    with session_factory() as session:
        reg.publish_new_version(session, "edge", b2, effective_at=t_switch)
        session.commit()

    with session_factory() as session:
        at_switch = reg.get_active_version(session, "edge", t_switch)
        assert at_switch is not None
        assert at_switch.rule_body == b2
        just_before = reg.get_active_version(session, "edge", t_switch - timedelta(microseconds=1))
        assert just_before is not None
        assert just_before.rule_body == b1
