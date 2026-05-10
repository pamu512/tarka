"""SQLAlchemy ORM models for the immutable rule registry."""

from __future__ import annotations

import uuid
from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, String, Text, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.schema import UniqueConstraint


class Base(DeclarativeBase):
    pass


class RuleVersion(Base):
    """One immutable revision of a named rule; temporal validity uses ``valid_from`` / ``valid_to``."""

    __tablename__ = "rule_versions"
    __table_args__ = (
        UniqueConstraint("rule_name", "content_hash", name="uq_rule_versions_rule_name_content_hash"),
        CheckConstraint(
            "(valid_to IS NULL) OR (valid_to > valid_from)",
            name="ck_rule_versions_valid_range",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    rule_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_body: Mapped[str] = mapped_column(Text, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<RuleVersion id={self.id} rule_name={self.rule_name!r} "
            f"hash={self.content_hash[:12]}…>"
        )
