"""Persist rule-engine evaluation trace and final actions to Postgres (Lekh ``decisions``)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.models.decision import DecisionORM

logger = logging.getLogger(__name__)


def _actions_from_rule_data(rule_data: dict[str, Any]) -> list[str]:
    raw = rule_data.get("actions")
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw]


def _final_decision(actions: list[str]) -> str:
    if not actions:
        return "NONE"
    return actions[0]


async def persist_lekh_decision(
    session: AsyncSession,
    *,
    entity_id: str,
    rule_data: dict[str, Any],
) -> int:
    """
    Insert one ``decisions`` row. When ``actions`` includes ``BLOCK``, ``blocking_rule_id`` must
    be present on ``rule_data`` (exact rule UUID string from the engine).
    """
    actions = _actions_from_rule_data(rule_data)
    trace_raw = rule_data.get("evaluation_trace")
    trace: list[Any] = trace_raw if isinstance(trace_raw, list) else []
    br = rule_data.get("blocking_rule_id")
    blocking_rule_id: str | None = None
    if isinstance(br, str) and br.strip():
        blocking_rule_id = br.strip()
    if "BLOCK" in actions and blocking_rule_id is None:
        msg = "blocking_rule_id required when rule_engine actions include BLOCK"
        logger.error("lekh_decision_invariant_failed entity_id=%s %s", entity_id, msg)
        raise ValueError(msg)

    row = DecisionORM(
        entity_id=entity_id,
        final_decision=_final_decision(actions),
        actions_json=actions,
        execution_trace_json=trace,
        blocking_rule_id=blocking_rule_id,
        raw_rule_engine_json=rule_data,
    )
    session.add(row)
    await session.flush()
    return int(row.id)
