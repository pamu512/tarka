from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class OrchestratorRun(Base):
    __tablename__ = "chitragupta_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    plugin_id: Mapped[str] = mapped_column(String(128))
    input_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    artifacts: Mapped[dict] = mapped_column(JSON, default=dict)
    emitter_logs: Mapped[list] = mapped_column(JSON, default=list)
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


engine = None
SessionLocal: async_sessionmaker[AsyncSession] | None = None


def configure_engine(url: str) -> None:
    global engine, SessionLocal
    engine = create_async_engine(url, echo=False)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    assert engine is not None
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session():
    assert SessionLocal is not None
    async with SessionLocal() as session:
        yield session
