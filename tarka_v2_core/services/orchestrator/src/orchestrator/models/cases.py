"""Lifecycle case persistence: durable investigation records anchored to audit rows.

``CaseORM`` maps to ``lifecycle_cases`` so it does not collide with ``tarka_shared.audit_trail.Case``
(the Shadow forensic ``cases`` table). The ``transaction_id`` column is a strict FK to
``audit_logs.id`` (the durable row created for that ingest / decision event).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from tarka_shared.audit_trail import AuditLog  # noqa: F401 — register FK target in metadata
from tarka_shared.database.session import Base


class CaseStatus(str, Enum):
    """Analyst-facing lifecycle states for a post-ingest investigation case."""

    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    PENDING_ACTION = "PENDING_ACTION"
    RESOLVED_FRAUD = "RESOLVED_FRAUD"
    RESOLVED_LEGIT = "RESOLVED_LEGIT"
    RESOLVED_AUTO = "RESOLVED_AUTO"


class StateTransitionError(ValueError):
    """Raised when ``transition_status`` rejects a disallowed or under-documented move."""


_RESOLVED = frozenset(
    {CaseStatus.RESOLVED_FRAUD, CaseStatus.RESOLVED_LEGIT, CaseStatus.RESOLVED_AUTO},
)
_REOPEN_TARGETS = frozenset(
    {
        CaseStatus.OPEN,
        CaseStatus.UNDER_REVIEW,
        CaseStatus.PENDING_ACTION,
    },
)
_FORWARD: dict[CaseStatus, frozenset[CaseStatus]] = {
    CaseStatus.OPEN: frozenset(
        {
            CaseStatus.UNDER_REVIEW,
            CaseStatus.PENDING_ACTION,
            CaseStatus.RESOLVED_FRAUD,
            CaseStatus.RESOLVED_LEGIT,
            CaseStatus.RESOLVED_AUTO,
        },
    ),
    CaseStatus.UNDER_REVIEW: frozenset(
        {
            CaseStatus.OPEN,
            CaseStatus.PENDING_ACTION,
            CaseStatus.RESOLVED_FRAUD,
            CaseStatus.RESOLVED_LEGIT,
            CaseStatus.RESOLVED_AUTO,
        },
    ),
    CaseStatus.PENDING_ACTION: frozenset(
        {
            CaseStatus.OPEN,
            CaseStatus.UNDER_REVIEW,
            CaseStatus.RESOLVED_FRAUD,
            CaseStatus.RESOLVED_LEGIT,
            CaseStatus.RESOLVED_AUTO,
        },
    ),
    CaseStatus.RESOLVED_FRAUD: frozenset(
        {CaseStatus.RESOLVED_LEGIT, CaseStatus.RESOLVED_AUTO},
    ),
    CaseStatus.RESOLVED_LEGIT: frozenset(
        {CaseStatus.RESOLVED_FRAUD, CaseStatus.RESOLVED_AUTO},
    ),
    CaseStatus.RESOLVED_AUTO: frozenset(
        {CaseStatus.RESOLVED_FRAUD, CaseStatus.RESOLVED_LEGIT},
    ),
}


def transition_status(
    current_status: CaseStatus,
    new_status: CaseStatus,
    *,
    reopen_reason: str | None = None,
) -> CaseStatus:
    """
    Validate and return the next status for a lifecycle case.

    Rules:
        * Transitions from ``RESOLVED_*`` to ``OPEN``, ``UNDER_REVIEW``, or ``PENDING_ACTION``
          require a non-empty ``reopen_reason`` (audit-grade accountability).
        * Moves among ``RESOLVED_FRAUD``, ``RESOLVED_LEGIT``, and ``RESOLVED_AUTO`` are allowed
          without a reopen reason (disposition correction).
        * All other moves must appear in the forward adjacency map.
    """
    if current_status == new_status:
        return new_status

    if current_status in _RESOLVED and new_status in _REOPEN_TARGETS:
        if reopen_reason is None or not str(reopen_reason).strip():
            raise StateTransitionError(
                f"cannot transition from {current_status.value} to {new_status.value} "
                "without a non-empty reopen_reason",
            )
        return new_status

    if current_status in _RESOLVED and new_status in _RESOLVED and current_status != new_status:
        return new_status

    allowed = _FORWARD.get(current_status, frozenset())
    if new_status not in allowed:
        raise StateTransitionError(
            f"illegal transition: {current_status.value} -> {new_status.value}"
        )
    return new_status


class CaseHistoryORM(Base):
    """Append-only case history: ingest linkage (``audit_log_id``) and/or status transitions."""

    __tablename__ = "case_history"
    __table_args__ = (
        # Ingest rows set ``audit_log_id``; API transitions leave it null — at most one ingest row per log.
        Index(
            "uq_case_history_audit_log_id",
            "audit_log_id",
            unique=True,
            sqlite_where=text("audit_log_id IS NOT NULL"),
            postgresql_where=text("audit_log_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("lifecycle_cases.case_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    audit_log_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("audit_logs.id", ondelete="CASCADE"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    #: Populated for ``PUT /v1/cases/{id}/status`` audit rows (ingest rows leave null).
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    auth_token_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    lifecycle_case: Mapped["CaseORM"] = relationship("CaseORM", back_populates="history_rows")
    audit_log: Mapped[AuditLog] = relationship(
        "AuditLog",
        foreign_keys=[audit_log_id],
        viewonly=True,
    )


class OrchestratorPollStateORM(Base):
    """Single-row cursor so the audit poller resumes after restarts."""

    __tablename__ = "orchestrator_poll_state"

    singleton_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_audit_log_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CaseORM(Base):
    """SQLAlchemy row: actionable investigation case tied to one ``AuditLog`` primary key."""

    __tablename__ = "lifecycle_cases"

    case_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    transaction_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("audit_logs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="FK to ``audit_logs.id`` for the first ingest event that opened this case.",
    )
    user_link_key: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        index=True,
        doc="Dedup key: ``metadata['user_id']`` when present, else ``entity_id``.",
    )
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=CaseStatus.OPEN.value,
        server_default=text(f"'{CaseStatus.OPEN.value}'"),
    )
    assignee_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Integer 0–100 derived from rule-engine / shadow risk signals at case creation.",
    )
    #: Analyst / dashboard tags (e.g. ``Dispute`` for chargeback inception).
    case_labels: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    #: Checkout / device session id copied from the original payment when filing a chargeback.
    linked_session_id: Mapped[str | None] = mapped_column(String(256), nullable=True)

    audit_log: Mapped[AuditLog] = relationship(
        "AuditLog",
        foreign_keys=[transaction_id],
        viewonly=True,
    )
    history_rows: Mapped[list["CaseHistoryORM"]] = relationship(
        "CaseHistoryORM",
        back_populates="lifecycle_case",
        cascade="all, delete-orphan",
    )


class Case(BaseModel):
    """Pydantic envelope for API and worker boundaries (mirrors ``CaseORM``)."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    case_id: UUID
    transaction_id: Annotated[
        int,
        Field(
            ...,
            description="``audit_logs.id`` for the transaction event under investigation.",
        ),
    ]
    status: CaseStatus
    assignee_id: str | None = None
    priority: Annotated[
        int,
        Field(
            ...,
            ge=0,
            le=100,
            description="0–100 priority snapshot from policy / AI scores when the case was filed.",
        ),
    ]

    @field_validator("status", mode="before")
    @classmethod
    def _coerce_status(cls, value: object) -> CaseStatus:
        if isinstance(value, CaseStatus):
            return value
        if isinstance(value, str):
            return CaseStatus(value)
        raise TypeError("status must be CaseStatus or str")


def priority_from_scores(*, rule_score: float | None = None, ai_score: float | None = None) -> int:
    """
    Derive a bounded integer priority from optional rule-engine and AI components.

    Uses the max of provided finite scores in ``[0, 100]``, otherwise ``0``.
    """
    candidates: list[float] = []
    for raw in (rule_score, ai_score):
        if raw is None:
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        if v == v and 0.0 <= v <= 100.0:  # not NaN
            candidates.append(v)
    if not candidates:
        return 0
    return int(round(max(candidates)))
