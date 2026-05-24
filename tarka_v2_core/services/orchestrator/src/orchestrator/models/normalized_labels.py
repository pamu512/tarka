"""Ground-truth label persistence (``normalized_labels`` table)."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import Boolean, DateTime, Index, String, Uuid
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, TypeEngine
from tarka_shared.database.session import Base

from orchestrator.models.cases import CaseStatus

SOURCE_TYPE_ANALYST_DISPOSITION = "ANALYST_DISPOSITION"
SOURCE_TYPE_CHARGEBACK = "CHARGEBACK"
_CASE_HISTORY_SOURCE_NAMESPACE = NAMESPACE_URL


class GroundTruthClass(str, Enum):
    FRAUD = "FRAUD"
    LEGITIMATE = "LEGITIMATE"


def _tags_column_type() -> TypeEngine[list[str]]:
    return ARRAY(String).with_variant(JSON(), "sqlite")


def ground_truth_class_for_resolved_status(status: CaseStatus) -> GroundTruthClass | None:
    """Map analyst terminal lifecycle statuses to consortium ground-truth classes."""
    if status == CaseStatus.RESOLVED_FRAUD:
        return GroundTruthClass.FRAUD
    if status == CaseStatus.RESOLVED_LEGIT:
        return GroundTruthClass.LEGITIMATE
    return None


def case_history_source_id(case_history_id: int) -> UUID:
    """Stable UUID anchor for polymorphic ``normalized_labels.source_id``."""
    if case_history_id < 1:
        raise ValueError("case_history_id must be a positive integer")
    return uuid5(_CASE_HISTORY_SOURCE_NAMESPACE, f"tarka:case_history:{case_history_id}")


def _normalize_tags(tags: list[str] | None, *, reason_code: str, resolved_status: str) -> list[str]:
    out: list[str] = ["analyst_disposition", resolved_status.strip()]
    rc = reason_code.strip()
    if rc:
        out.append(f"reason:{rc}")
    if tags:
        for raw in tags:
            token = str(raw or "").strip()
            if token and token not in out:
                out.append(token[:128])
    return out


class NormalizedLabelORM(Base):
    """Maps to ``normalized_labels`` (see ``migrations/20260525_001_operational_signals.sql``)."""

    __tablename__ = "normalized_labels"
    __table_args__ = (
        Index("idx_normalized_labels_entity_created_at", "entity_id", "created_at"),
        Index("idx_normalized_labels_ground_truth_created_at", "ground_truth_class", "created_at"),
        Index("idx_normalized_labels_source_type_source_id", "source_type", "source_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(512), nullable=False)
    ground_truth_class: Mapped[str] = mapped_column(String(32), nullable=False)
    tags: Mapped[list[str]] = mapped_column(
        _tags_column_type(),
        nullable=False,
        default=list,
        server_default="{}",
    )
    propagated_to_consortium: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


class NormalizedLabelDAO:
    """Async helpers for :class:`NormalizedLabelORM` (caller owns session / transaction)."""

    @staticmethod
    def _normalize_entity_id(entity_id: str) -> str:
        token = (entity_id or "").strip()
        if not token or len(token) > 512:
            raise ValueError("entity_id must be a non-empty string up to 512 characters")
        return token

    @staticmethod
    def _normalize_ground_truth_class(value: GroundTruthClass | str) -> str:
        if isinstance(value, GroundTruthClass):
            token = value.value
        else:
            token = str(value or "").strip().upper()
        if token not in {GroundTruthClass.FRAUD.value, GroundTruthClass.LEGITIMATE.value}:
            raise ValueError("ground_truth_class must be FRAUD or LEGITIMATE")
        return token

    @classmethod
    async def append_structural_tags(
        cls,
        session: AsyncSession,
        label_id: UUID,
        structural_tags: list[str],
    ) -> NormalizedLabelORM:
        row = await session.get(NormalizedLabelORM, label_id)
        if row is None:
            raise LookupError(f"normalized label not found: {label_id}")
        merged = list(row.tags or [])
        seen = set(merged)
        for raw in structural_tags:
            token = str(raw or "").strip()
            if not token or token in seen:
                continue
            seen.add(token)
            merged.append(token[:128])
        row.tags = merged
        await session.flush()
        await session.refresh(row)
        return row

    @classmethod
    async def mark_propagated(
        cls,
        session: AsyncSession,
        label_id: UUID,
    ) -> NormalizedLabelORM:
        row = await session.get(NormalizedLabelORM, label_id)
        if row is None:
            raise LookupError(f"normalized label not found: {label_id}")
        row.propagated_to_consortium = True
        await session.flush()
        await session.refresh(row)
        return row

    @classmethod
    async def create_operational_signal_label(
        cls,
        session: AsyncSession,
        *,
        operational_signal_id: UUID,
        source_type: str,
        entity_id: str,
        ground_truth_class: GroundTruthClass,
        tags: list[str] | None = None,
    ) -> NormalizedLabelORM:
        """Insert a label row anchored to ``operational_signals.id`` in the caller's transaction."""
        source_token = (source_type or "").strip()
        if not source_token:
            raise ValueError("source_type must be a non-empty string")
        merged_tags: list[str] = []
        seen: set[str] = set()
        for raw in tags or []:
            token = str(raw or "").strip()
            if not token or token in seen:
                continue
            seen.add(token)
            merged_tags.append(token[:128])
        row = NormalizedLabelORM(
            source_type=source_token,
            source_id=operational_signal_id,
            entity_id=cls._normalize_entity_id(entity_id),
            ground_truth_class=cls._normalize_ground_truth_class(ground_truth_class),
            tags=merged_tags,
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)
        return row

    @classmethod
    async def create_analyst_disposition(
        cls,
        session: AsyncSession,
        *,
        case_history_id: int,
        entity_id: str,
        ground_truth_class: GroundTruthClass,
        reason_code: str,
        resolved_status: str,
        tags: list[str] | None = None,
    ) -> NormalizedLabelORM:
        """Insert a label row for a terminal analyst case disposition in the caller's transaction."""
        row = NormalizedLabelORM(
            source_type=SOURCE_TYPE_ANALYST_DISPOSITION,
            source_id=case_history_source_id(case_history_id),
            entity_id=cls._normalize_entity_id(entity_id),
            ground_truth_class=cls._normalize_ground_truth_class(ground_truth_class),
            tags=_normalize_tags(tags, reason_code=reason_code, resolved_status=resolved_status),
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)
        return row
