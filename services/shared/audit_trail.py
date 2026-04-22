from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

"""Immutable field-level audit trail.

Tracks all mutations to cases, rules, and entities with before/after snapshots.

Usage::

    from audit_trail import AuditTrail, setup_audit_trail
    trail = setup_audit_trail(app)  # creates table and attaches to app.state

    await trail.record(
        session=db_session,
        actor="analyst@corp.com",
        action="update_case",
        resource_type="case",
        resource_id="case-uuid",
        changes={"status": {"old": "open", "new": "escalated"}},
    )
"""
_JSON_COL = JSON().with_variant(JSONB(), "postgresql")


class AuditEntry:
    """Mixin: add this to your Base to create the audit_trail table."""

    __tablename__ = "audit_trail"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    actor: Mapped[str] = mapped_column(String(256))
    action: Mapped[str] = mapped_column(String(64), index=True)
    resource_type: Mapped[str] = mapped_column(String(64), index=True)
    resource_id: Mapped[str] = mapped_column(String(256), index=True)
    changes: Mapped[dict] = mapped_column(_JSON_COL)
    metadata_extra: Mapped[dict | None] = mapped_column(_JSON_COL, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def create_audit_model(Base: type[DeclarativeBase]):
    """Dynamically create an AuditEntry model bound to the given Base."""

    class AuditRecord(Base, AuditEntry):
        pass

    return AuditRecord


class AuditTrail:
    def __init__(self, model_class: type) -> None:
        self._model = model_class

    async def record(
        self,
        session: AsyncSession,
        actor: str,
        action: str,
        resource_type: str,
        resource_id: str,
        changes: dict[str, Any],
        tenant_id: str = "",
        metadata_extra: dict[str, Any] | None = None,
    ) -> None:
        entry = self._model(
            tenant_id=tenant_id,
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            changes=changes,
            metadata_extra=metadata_extra,
        )
        session.add(entry)

    async def get_history(
        self,
        session: AsyncSession,
        resource_type: str,
        resource_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        from sqlalchemy import select

        q = (
            select(self._model)
            .where(self._model.resource_type == resource_type, self._model.resource_id == resource_id)
            .order_by(self._model.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(q)
        return [
            {
                "id": str(row.id),
                "actor": row.actor,
                "action": row.action,
                "changes": row.changes,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in result.scalars().all()
        ]

    def diff(self, old: dict[str, Any], new: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Compute field-level diff between old and new state."""
        changes: dict[str, dict[str, Any]] = {}
        all_keys = set(old) | set(new)
        for k in all_keys:
            ov = old.get(k)
            nv = new.get(k)
            if ov != nv:
                changes[k] = {"old": ov, "new": nv}
        return changes
