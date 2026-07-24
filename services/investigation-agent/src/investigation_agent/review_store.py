from __future__ import annotations

from typing import Any, Literal

from investigation_agent import agent_run_store

"""Compatibility API over the unified AgentRun/review SQLite store."""


def db_path() -> str:
    return str(agent_run_store.db_path())


def reset_connection_for_tests() -> None:
    agent_run_store.reset_connection_for_tests()


def save_review(
    *,
    turn_id: str,
    tenant_id: str,
    analyst_id: str,
    status: Literal["approved", "rejected"],
    note: str | None,
) -> int:
    return agent_run_store.save_review_record(
        turn_id=turn_id,
        tenant_id=tenant_id,
        analyst_id=analyst_id,
        status=status,
        note=note,
    )


def latest_review(turn_id: str, tenant_id: str) -> dict[str, Any] | None:
    return agent_run_store.latest_review(turn_id, tenant_id)


def review_history(
    turn_id: str,
    tenant_id: str,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    return agent_run_store.review_history(
        turn_id,
        tenant_id,
        limit=limit,
    )


def review_metrics(tenant_id: str, days: float = 30.0) -> dict[str, Any]:
    return agent_run_store.review_metrics(tenant_id, days)
