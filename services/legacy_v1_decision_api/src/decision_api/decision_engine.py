"""Postgres audit helpers for rule evaluation; Rust FFI lives in :mod:`decision_api.rust_rule_engine_ffi`."""

from __future__ import annotations

from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from decision_api.models import AuditRecord
from decision_api.rust_rule_engine_ffi import (
    evaluate_cached_packs_via_rust,
    evaluate_json_rules_via_rust,
    parse_ast_malformed_detail,
    rust_json_rules_engine_available,
    should_use_rust_json_engine,
    sync_rust_packs_from_cache,
)

__all__ = [
    "DecisionEngine",
    "evaluate_cached_packs_via_rust",
    "evaluate_json_rules_via_rust",
    "finalize_audit_after_evaluation",
    "parse_ast_malformed_detail",
    "rust_json_rules_engine_available",
    "should_use_rust_json_engine",
    "sync_rust_packs_from_cache",
]


class DecisionEngine:
    """Coordinates durable audit I/O (Python) and rule evaluation (Rust when available)."""

    async def commit_pre_rule_evaluation_audit(
        self,
        session: AsyncSession,
        *,
        trace_id: Any,
        tenant_id: str,
        entity_id: str,
        event_type: str,
        features: dict[str, Any],
        redis_tags: list[str],
        signal_tags: list[str],
        snapshot: dict[str, Any],
    ) -> None:
        """Persist ``decision_audit`` with ``decision='pending'`` then commit before calling Rust."""
        row = AuditRecord(
            trace_id=trace_id,
            tenant_id=tenant_id,
            entity_id=entity_id,
            event_type=event_type,
            decision="pending",
            score=0.0,
            tags=list(signal_tags),
            rule_hits=[],
            payload_snapshot={
                "phase": "pre_rule_engine",
                "feature_key_sample": sorted(features.keys())[:200],
                "redis_tags": list(redis_tags),
                "signal_tags": list(signal_tags),
                **snapshot,
            },
        )
        session.add(row)
        await session.commit()


async def finalize_audit_after_evaluation(
    session: AsyncSession,
    *,
    trace_id: Any,
    decision: str,
    score: float,
    tags: list[str],
    rule_hits: list[str],
    payload_snapshot: dict[str, Any],
) -> None:
    """Update the row written by :meth:`DecisionEngine.commit_pre_rule_evaluation_audit`."""
    await session.execute(
        update(AuditRecord)
        .where(AuditRecord.trace_id == trace_id)
        .values(
            decision=decision,
            score=score,
            tags=tags,
            rule_hits=rule_hits,
            payload_snapshot=payload_snapshot,
        )
    )
    await session.commit()
