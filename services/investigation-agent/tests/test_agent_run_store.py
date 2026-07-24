from __future__ import annotations

import pytest
from decision_intelligence import new_agent_run
from investigation_agent import agent_run_store, review_store


def test_agent_run_restart_readback_is_tenant_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTIGATION_DATA_DIR", str(tmp_path))
    agent_run_store.reset_connection_for_tests()
    run = new_agent_run(
        tenant_id="t1",
        prompt="Investigate high amount activity",
        model_provider="openai_compatible",
        model_revision="model-1",
        tool_calls=[{"tool": "search_knowledge", "result": {"hits": []}}],
        evidence_ids=["ev-1"],
        concept_ids=["rules/high-amount"],
        claims=[{"text": "High amount activity.", "source": "tool"}],
        uncertainty={"abstain": False},
        review_state="pending",
    ).to_dict()

    status = agent_run_store.persist_agent_run(
        run,
        analyst_id="analyst-1",
        turn_id="turn-1",
    )
    agent_run_store.reset_connection_for_tests()

    loaded = agent_run_store.get_agent_run(
        tenant_id="t1",
        agent_run_id=run["agent_run_id"],
    )
    other_tenant = agent_run_store.get_agent_run(
        tenant_id="t2",
        agent_run_id=run["agent_run_id"],
    )

    assert status == "persisted"
    assert loaded == run
    assert loaded["prompt_hash"]
    assert loaded["concept_ids"] == ["rules/high-amount"]
    assert loaded["review_state"] == "pending"
    assert other_tenant is None
    agent_run_store.reset_connection_for_tests()


def test_agent_run_emergency_audit_remains_tenant_readable_when_sqlite_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTIGATION_DATA_DIR", str(tmp_path))
    agent_run_store.reset_connection_for_tests()
    run = new_agent_run(
        tenant_id="t1",
        prompt="Investigate fallback persistence",
        model_provider="deterministic",
        model_revision="tools-only-v1",
        tool_calls=[],
        evidence_ids=[],
        concept_ids=[],
        claims=[{"text": "Persistence fallback exercised.", "source": "unknown"}],
        uncertainty={"persistence_degraded": True},
        review_state="pending",
    ).to_dict()

    def _sqlite_unavailable(*_args, **_kwargs):
        raise OSError("sqlite unavailable")

    monkeypatch.setattr(agent_run_store, "_persist_sqlite", _sqlite_unavailable)
    status = agent_run_store.persist_agent_run(
        run,
        analyst_id="analyst-1",
        turn_id="turn-fallback",
    )
    monkeypatch.setattr(agent_run_store, "_get_conn", _sqlite_unavailable)

    loaded = agent_run_store.get_agent_run(
        tenant_id="t1",
        agent_run_id=run["agent_run_id"],
    )
    other_tenant = agent_run_store.get_agent_run(
        tenant_id="t2",
        agent_run_id=run["agent_run_id"],
    )
    updated = agent_run_store.update_review_state(
        tenant_id="t1",
        turn_id="turn-fallback",
        review_state="approved",
    )
    reviewed = agent_run_store.get_agent_run(
        tenant_id="t1",
        agent_run_id=run["agent_run_id"],
    )

    assert status == "degraded_emergency"
    assert loaded == run
    assert other_tenant is None
    assert updated is True
    assert reviewed["review_state"] == "approved"


def _persist_pending_run(*, tenant_id: str, turn_id: str) -> dict:
    run = new_agent_run(
        tenant_id=tenant_id,
        prompt="Review this investigation",
        model_provider="deterministic",
        model_revision="tools-only-v1",
        tool_calls=[],
        evidence_ids=[],
        concept_ids=[],
        claims=[],
        uncertainty={},
        review_state="pending",
    ).to_dict()
    assert (
        agent_run_store.persist_agent_run(
            run,
            analyst_id="maker",
            turn_id=turn_id,
        )
        == "persisted"
    )
    return run


def test_review_and_agent_run_are_atomic_and_retry_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTIGATION_DATA_DIR", str(tmp_path))
    agent_run_store.reset_connection_for_tests()
    run = _persist_pending_run(tenant_id="t1", turn_id="turn-atomic")

    first_id = agent_run_store.save_review_transactionally(
        turn_id="turn-atomic",
        tenant_id="t1",
        analyst_id="checker",
        status="approved",
        note="verified",
    )
    retry_id = agent_run_store.save_review_transactionally(
        turn_id="turn-atomic",
        tenant_id="t1",
        analyst_id="checker",
        status="approved",
        note="verified",
    )

    reviewed = agent_run_store.get_agent_run(
        tenant_id="t1",
        agent_run_id=run["agent_run_id"],
    )
    metrics = review_store.review_metrics("t1")

    assert retry_id == first_id
    assert reviewed["review_state"] == "approved"
    assert review_store.latest_review("turn-atomic", "t1")["id"] == first_id
    assert metrics["total_reviews"] == 1
    assert metrics["approved"] == 1
    agent_run_store.reset_connection_for_tests()


def test_review_transaction_failure_rolls_back_and_retry_succeeds(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTIGATION_DATA_DIR", str(tmp_path))
    agent_run_store.reset_connection_for_tests()
    run = _persist_pending_run(tenant_id="t1", turn_id="turn-rollback")
    original_update = agent_run_store._update_agent_run_review_payload

    def _fail_update(*_args, **_kwargs):
        raise OSError("injected transaction failure")

    monkeypatch.setattr(
        agent_run_store,
        "_update_agent_run_review_payload",
        _fail_update,
    )
    with pytest.raises(agent_run_store.AgentRunPersistenceError):
        agent_run_store.save_review_transactionally(
            turn_id="turn-rollback",
            tenant_id="t1",
            analyst_id="checker",
            status="rejected",
            note="needs work",
        )

    assert review_store.latest_review("turn-rollback", "t1") is None
    assert (
        agent_run_store.get_agent_run(
            tenant_id="t1",
            agent_run_id=run["agent_run_id"],
        )["review_state"]
        == "pending"
    )

    monkeypatch.setattr(
        agent_run_store,
        "_update_agent_run_review_payload",
        original_update,
    )
    review_id = agent_run_store.save_review_transactionally(
        turn_id="turn-rollback",
        tenant_id="t1",
        analyst_id="checker",
        status="rejected",
        note="needs work",
    )

    assert review_id > 0
    assert review_store.review_metrics("t1")["total_reviews"] == 1
    assert (
        agent_run_store.get_agent_run(
            tenant_id="t1",
            agent_run_id=run["agent_run_id"],
        )["review_state"]
        == "rejected"
    )
    agent_run_store.reset_connection_for_tests()
