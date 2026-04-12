import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from decision_api.db import Base

# JSON on SQLite (tests/CI); JSONB on PostgreSQL (Alembic migrations use JSONB explicitly).
_JSON_COL = JSON().with_variant(JSONB(), "postgresql")


class AuditRecord(Base):
    __tablename__ = "decision_audit"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    entity_id: Mapped[str] = mapped_column(String(512), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(32))
    score: Mapped[float] = mapped_column(Float)
    tags: Mapped[list] = mapped_column(_JSON_COL, default=list)
    rule_hits: Mapped[list] = mapped_column(_JSON_COL, default=list)
    payload_snapshot: Mapped[dict | None] = mapped_column(_JSON_COL, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
