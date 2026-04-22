import os
from collections.abc import AsyncGenerator
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import text

from case_api.config import settings

_DEFAULT_LOCAL_DB_URL = "sqlite+aiosqlite:///./data/case-api-dev.db"
_ALEMBIC_VERSION_TABLE = "alembic_version_case_api"
_active_database_url = settings.database_url
_fallback_activated = False
_fallback_reason: str | None = None
_bootstrap_mode = "unknown"


def _configure_engine(url: str):
    return create_async_engine(url, echo=False, pool_pre_ping=True)


engine = _configure_engine(_active_database_url)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def _is_sqlite(url: str) -> bool:
    return "sqlite" in url.lower()


def _sync_url_for_alembic(url: str) -> str:
    if "+asyncpg" in url:
        return url.replace("postgresql+asyncpg", "postgresql+psycopg")
    if "sqlite+aiosqlite" in url:
        return url.replace("sqlite+aiosqlite://", "sqlite://")
    return url


def _resolve_local_fallback_url() -> str:
    override = (os.environ.get("CASE_API_LOCAL_DB_URL") or "").strip()
    if override:
        return override
    app_root = Path(__file__).resolve().parent.parent.parent
    db_path = (app_root / "data" / "case-api-dev.db").resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{db_path}"


async def _activate_local_fallback() -> None:
    global engine, SessionLocal, _active_database_url, _fallback_activated
    fallback_url = _resolve_local_fallback_url()
    if _active_database_url == fallback_url:
        _fallback_activated = True
        return
    await engine.dispose()
    _active_database_url = fallback_url
    engine = _configure_engine(_active_database_url)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    _fallback_activated = True


def active_database_url() -> str:
    return _active_database_url


def active_database_backend() -> str:
    return "sqlite" if _is_sqlite(_active_database_url) else "postgresql"


def using_local_fallback() -> bool:
    return _fallback_activated


def fallback_reason() -> str | None:
    return _fallback_reason


def bootstrap_mode() -> str:
    return _bootstrap_mode


def public_database_url() -> str:
    if _is_sqlite(_active_database_url):
        return _active_database_url
    parsed = urlparse(_active_database_url)
    if not parsed.scheme:
        return _active_database_url
    userinfo = ""
    if parsed.username:
        userinfo = parsed.username
        if parsed.password is not None:
            userinfo = f"{userinfo}:***"
        userinfo = f"{userinfo}@"
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    return parsed._replace(netloc=f"{userinfo}{host}{port}", query="", fragment="").geturl()


def _app_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def expected_migration_heads() -> list[str]:
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(str(_app_root() / "alembic.ini"))
        script = ScriptDirectory.from_config(cfg)
        return sorted(script.get_heads())
    except Exception:
        return []


async def current_migration_versions() -> tuple[list[str], str | None]:
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(text(f"SELECT version_num FROM {_ALEMBIC_VERSION_TABLE}"))
            versions = sorted(str(r[0]) for r in rows if r and r[0])
            return versions, None
    except Exception as exc:
        return [], f"{exc.__class__.__module__}.{exc.__class__.__name__}"


async def migration_status() -> dict[str, object]:
    expected = expected_migration_heads()
    current, current_err = await current_migration_versions()
    state = "in_sync"
    note = "Migration revision(s) match expected Alembic head(s)."

    if using_local_fallback():
        state = "fallback_sqlite"
        note = "DB is running in local sqlite fallback; migration drift against primary DB cannot be asserted."
    elif not expected:
        state = "expected_head_unavailable"
        note = "Unable to resolve expected Alembic head(s) from migration scripts."
    elif current_err:
        state = "current_revision_unavailable"
        note = "Unable to read current DB migration revision(s)."
    elif not current:
        state = "not_initialized"
        note = "No migration revision rows found in DB version table."
    elif set(current) != set(expected):
        state = "drift"
        note = "Current DB revision(s) differ from expected Alembic head(s)."

    return {
        "state": state,
        "expected_heads": expected,
        "current_versions": current,
        "current_versions_error": current_err,
        "database_backend": active_database_backend(),
        "database_url": public_database_url(),
        "database_fallback_active": using_local_fallback(),
        "database_fallback_reason": fallback_reason(),
        "database_bootstrap_mode": bootstrap_mode(),
        "runbook_hint": "Run `alembic upgrade head` against case-api DB and restart service when state=drift.",
        "note": note,
    }


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


def _can_use_local_fallback(exc: Exception) -> bool:
    if isinstance(exc, SQLAlchemyError):
        return True
    return exc.__class__.__module__.startswith("alembic")


async def init_db() -> None:
    global _fallback_reason, _bootstrap_mode
    from case_api import models as _models  # noqa: F401

    try:
        if _is_sqlite(_active_database_url):
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            _bootstrap_mode = "sqlite_direct"
            return

        os.environ["ALEMBIC_SYNC_DATABASE_URL"] = _sync_url_for_alembic(_active_database_url)
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(_app_root() / "alembic.ini"))
        command.upgrade(cfg, "head")
        _bootstrap_mode = "alembic_head"
    except Exception as exc:
        # Local resilience: only DB bootstrap/migration failures trigger sqlite fallback.
        if settings.case_api_production_mode or not _can_use_local_fallback(exc):
            raise
        _fallback_reason = f"{exc.__class__.__module__}.{exc.__class__.__name__}"
        await _activate_local_fallback()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _bootstrap_mode = "sqlite_fallback"
