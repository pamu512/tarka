"""Persist orchestration outcomes to ``audit_logs`` and materialize lifecycle cases in the background."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool
from tarka_shared.audit_trail import AuditLog, Case
from tarka_shared.case_status import DEFAULT_CASE_STATUS
from tarka_shared.data.tenant_constants import DEFAULT_TENANT_ID

from orchestrator.models.cases import (
    CaseHistoryORM,
    CaseORM,
    CaseStatus,
    OrchestratorPollStateORM,
    priority_from_scores,
)

logger = logging.getLogger(__name__)

ORCHESTRATOR_AUDIT_SOURCE = "orchestrator_orchestrate"
CURSOR_KEY = "audit_cursor"
TRIGGER_ACTIONS_FOR_LIFECYCLE = frozenset({"BLOCK", "FLAG", "SHADOW_REVIEW"})


def resolve_audit_database_url(*, override: str | None = None) -> str | None:
    import os

    raw = (override or os.environ.get("ORCHESTRATOR_AUDIT_DATABASE_URL") or "").strip()
    if raw:
        return raw
    return os.environ.get("SHADOW_DATABASE_URL", "").strip() or None


def _user_link_key(metadata: dict[str, Any], entity_id: str) -> str:
    uid = metadata.get("user_id")
    if uid is not None and str(uid).strip() != "":
        return str(uid)
    return entity_id


async def _ensure_shadow_case_row(session: AsyncSession, entity_id: str) -> None:
    """Ensure a ``cases`` row exists so ``audit_logs.case_id`` FK can succeed."""
    existing = await session.scalar(select(Case.id).where(Case.id == entity_id))
    if existing is not None:
        return
    try:
        async with session.begin_nested():
            session.add(
                Case(
                    id=entity_id,
                    tenant_id=DEFAULT_TENANT_ID,
                    name="orchestrator-transaction-anchor",
                    dataset_path=None,
                    is_active=False,
                    status=DEFAULT_CASE_STATUS,
                ),
            )
            await session.flush()
    except IntegrityError:
        # Concurrent ingest created the anchor row in another transaction.
        return


async def persist_orchestrator_audit_log(
    session: AsyncSession,
    *,
    entity_id: str,
    metadata: dict[str, Any],
    actions: list[str],
    rule_data: dict[str, Any],
    shadow_data: dict[str, Any] | None,
) -> int | None:
    """
    Insert a marker ``AuditLog`` row when policy actions warrant a lifecycle case.

    Returns the new ``audit_logs.id``, or ``None`` when no triggering action is present.
    """
    hits = [a for a in actions if a in TRIGGER_ACTIONS_FOR_LIFECYCLE]
    if not hits:
        return None

    await _ensure_shadow_case_row(session, entity_id)
    user_key = _user_link_key(metadata, entity_id)
    rs: float | None = None
    if isinstance(shadow_data, dict) and shadow_data.get("risk_score") is not None:
        try:
            rs = float(shadow_data["risk_score"])
        except (TypeError, ValueError):
            rs = None
    prio = priority_from_scores(
        rule_score=rule_data.get("risk_score") if isinstance(rule_data.get("risk_score"), (int, float)) else None,
        ai_score=rs,
    )
    payload: dict[str, Any] = {
        "source": ORCHESTRATOR_AUDIT_SOURCE,
        "actions": hits,
        "entity_id": entity_id,
        "user_id": metadata.get("user_id"),
        "user_link_key": user_key,
        "priority_hint": prio,
    }
    ing = str(metadata.get("ingestion_type") or "").upper()
    if ing == "CHARGEBACK":
        payload["ingestion_type"] = "CHARGEBACK"
        ls = metadata.get("linked_session_id") or metadata.get("session_id")
        if ls is not None and str(ls).strip() != "":
            payload["linked_session_id"] = str(ls).strip()
        oe = metadata.get("original_entity_id")
        if oe is not None and str(oe).strip() != "":
            payload["original_entity_id"] = str(oe).strip()
        raw_tags = metadata.get("case_tags") if isinstance(metadata.get("case_tags"), list) else metadata.get("labels")
        if isinstance(raw_tags, list) and raw_tags:
            payload["case_tags"] = [str(x) for x in raw_tags if str(x).strip()]
        else:
            payload["case_tags"] = ["Dispute"]
    log = AuditLog(
        case_id=entity_id,
        action_taken=json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
        code_executed=None,
        agent_notes=None,
    )
    session.add(log)
    await session.flush()
    return int(log.id)


async def process_new_audit_logs(session: AsyncSession) -> None:
    """
    Consume new ``AuditLog`` rows written by the orchestrator and upsert ``lifecycle_cases`` / ``case_history``.

    Idempotent per ``audit_log_id`` via ``case_history`` uniqueness.
    """
    cursor = await session.scalar(
        select(OrchestratorPollStateORM).where(OrchestratorPollStateORM.singleton_key == CURSOR_KEY),
    )
    if cursor is None:
        cursor = OrchestratorPollStateORM(singleton_key=CURSOR_KEY, last_audit_log_id=0)
        session.add(cursor)
        await session.flush()

    stmt = (
        select(AuditLog)
        .where(AuditLog.id > cursor.last_audit_log_id)
        .order_by(AuditLog.id.asc())
        .limit(500)
    )
    logs = (await session.scalars(stmt)).all()
    if not logs:
        return

    now = datetime.now(UTC)
    since = now - timedelta(hours=24)
    max_id = cursor.last_audit_log_id

    for log in logs:
        max_id = max(max_id, int(log.id))
        try:
            body = json.loads(log.action_taken)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(body, dict):
            continue
        if body.get("source") != ORCHESTRATOR_AUDIT_SOURCE:
            continue
        acts = set(body.get("actions") or [])
        if not acts & TRIGGER_ACTIONS_FOR_LIFECYCLE:
            continue

        user_key = str(body.get("user_link_key") or body.get("user_id") or body.get("entity_id"))
        entity_id = str(body["entity_id"])
        try:
            prio = int(body.get("priority_hint") or 0)
        except (TypeError, ValueError):
            prio = 0
        prio = max(0, min(100, prio))

        existing = (
            await session.execute(
                select(CaseORM)
                .where(
                    CaseORM.user_link_key == user_key,
                    CaseORM.opened_at >= since,
                )
                .order_by(CaseORM.opened_at.asc())
                .limit(1),
            )
        ).scalar_one_or_none()

        if existing is not None:
            try:
                async with session.begin_nested():
                    session.add(
                        CaseHistoryORM(case_id=existing.case_id, audit_log_id=int(log.id)),
                    )
                    await session.flush()
            except IntegrityError:
                logger.debug(
                    "case_history_skip_duplicate audit_log_id=%s case_id=%s",
                    log.id,
                    existing.case_id,
                )
        else:
            cid = str(uuid.uuid4())
            raw_tags = body.get("case_tags")
            case_labels: list[str] = []
            if isinstance(raw_tags, list):
                case_labels = [str(x) for x in raw_tags if str(x).strip()]
            if str(body.get("ingestion_type") or "").upper() == "CHARGEBACK" and not case_labels:
                case_labels = ["Dispute"]
            linked_sid = body.get("linked_session_id")
            linked_sid_s = str(linked_sid).strip() if linked_sid is not None and str(linked_sid).strip() else None
            session.add(
                CaseORM(
                    case_id=cid,
                    transaction_id=int(log.id),
                    user_link_key=user_key,
                    entity_id=entity_id,
                    opened_at=now,
                    status=CaseStatus.OPEN.value,
                    priority=prio,
                    case_labels=list(case_labels),
                    linked_session_id=linked_sid_s,
                ),
            )
            session.add(CaseHistoryORM(case_id=cid, audit_log_id=int(log.id)))
            await session.flush()

    cursor.last_audit_log_id = max_id
    await session.flush()


def build_audit_engine(url: str) -> AsyncEngine:
    """Create async engine; use ``StaticPool`` for in-memory SQLite (tests)."""
    kw: dict[str, Any] = {"pool_pre_ping": True}
    if ":memory:" in url:
        kw["connect_args"] = {"check_same_thread": False}
        kw["poolclass"] = StaticPool
    return create_async_engine(url, **kw)


async def run_audit_poll_once(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Process one batch (used from tests and manual diagnostics)."""
    async with session_factory() as session:
        async with session.begin():
            await process_new_audit_logs(session)
