"""Postgres-compatible audit table for AI / tool calls (NATS OSINT, etc.).

Create in Postgres (example):

.. code-block:: sql

    CREATE TABLE ai_tool_logs (
        id SERIAL PRIMARY KEY,
        tool_name VARCHAR(128) NOT NULL,
        nats_subject VARCHAR(256) NOT NULL,
        reply_inbox VARCHAR(256),
        request_payload_exact TEXT NOT NULL,
        response_payload_exact TEXT,
        error TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_ai_tool_logs_tool_name ON ai_tool_logs (tool_name);
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for the ``shadow`` package."""


class AIToolLogORM(Base):
    """
    One row per tool invocation.

    ``request_payload_exact`` stores the **exact** UTF-8 JSON string bytes sent on the wire
    (stable ``json.dumps(..., separators=(',', ':'))``) so audits match OSINT / NATS payloads bit-for-bit in text form.
    """

    __tablename__ = "ai_tool_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    nats_subject: Mapped[str] = mapped_column(String(256), nullable=False)
    reply_inbox: Mapped[str | None] = mapped_column(String(256), nullable=True)
    request_payload_exact: Mapped[str] = mapped_column(Text(), nullable=False)
    response_payload_exact: Mapped[str | None] = mapped_column(Text(), nullable=True)
    error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        insert_default=lambda: datetime.now(UTC),
    )
