"""Micro-dev first-run onboarding: SQLite filesystem permissions + DuckDB native bindings.

Exposes HTTP 200 on per-check verify routes only when the local infrastructure check passes.
Used by the SPA to gate the main dashboard until all required checks succeed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy.engine import make_url

from tarka_core.internal_monitor import InternalMonitor

from decision_api.db import ENGINE_KIND, engine

router = APIRouter(prefix="/v1/micro-dev/onboarding", tags=["micro-dev-onboarding"])


def _sqlite_database_path() -> Path | None:
    """Filesystem path to the SQLite DB file when ENGINE_KIND is sqlite; else None."""
    if ENGINE_KIND != "sqlite":
        return None
    u = make_url(str(engine.url))
    db = (u.database or "").strip()
    if not db:
        return None
    p = Path(db)
    return p.resolve() if p.is_absolute() else (Path.cwd() / p).resolve()


def _analytics_store_raw() -> str:
    return (os.environ.get("TARKA_ANALYTICS_STORE") or "clickhouse").strip().lower()


def _analytics_uses_duckdb() -> bool:
    return _analytics_store_raw() in ("duck", "duckdb", "local")


def _public_probe_detail(
    reason_code: str, detail: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Strip filesystem paths and exception text before returning to HTTP clients."""
    out: dict[str, Any] = {"reason_code": reason_code}
    if not detail:
        return out
    for key in ("engine", "detail", "analytics_store"):
        if key in detail:
            out[key] = detail[key]
    return out


def _probe_sqlite_permissions() -> tuple[bool, str, dict[str, Any]]:
    path = _sqlite_database_path()
    if path is None:
        return (
            True,
            "not_applicable",
            {"engine": ENGINE_KIND, "detail": "SQLite audit plane is not active."},
        )

    parent = path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return (
            False,
            "sqlite_parent_mkdir_failed",
            {
                "engine": ENGINE_KIND,
                "detail": "SQLite parent directory is not writable.",
            },
        )

    if not os.access(parent, os.W_OK | os.X_OK):
        return (
            False,
            "sqlite_parent_not_writable",
            {
                "engine": ENGINE_KIND,
                "detail": "SQLite parent directory is not writable.",
            },
        )

    if path.exists():
        if not os.access(path, os.R_OK | os.W_OK):
            return (
                False,
                "sqlite_file_not_rw",
                {
                    "engine": ENGINE_KIND,
                    "detail": "SQLite database file is not readable/writable.",
                },
            )
    else:
        try:
            path.touch(mode=0o644, exist_ok=True)
        except OSError:
            return (
                False,
                "sqlite_touch_failed",
                {
                    "engine": ENGINE_KIND,
                    "detail": "SQLite database file could not be created.",
                },
            )

    return True, "ok", {"engine": ENGINE_KIND, "detail": "SQLite permissions OK."}


def _probe_duckdb_bindings() -> tuple[bool, str, dict[str, Any]]:
    if not _analytics_uses_duckdb():
        return (
            True,
            "not_applicable",
            {
                "analytics_store": _analytics_store_raw(),
                "detail": "DuckDB OLAP store is not configured.",
            },
        )

    try:
        from analytics.engine import DuckDBEngine
    except ImportError:  # pragma: no cover
        return (
            False,
            "duckdb_import_failed",
            {
                "analytics_store": _analytics_store_raw(),
                "detail": "DuckDB bindings are not installed.",
            },
        )

    eng = None
    try:
        eng = DuckDBEngine.from_env()
        res = eng.execute_query("SELECT 1 AS ok", ())
        ok = bool(res.rows) and res.rows[0][0] == 1
        if not ok:
            return (
                False,
                "duckdb_unexpected_result",
                {
                    "analytics_store": _analytics_store_raw(),
                    "detail": "DuckDB probe returned an unexpected result.",
                },
            )
        return (
            True,
            "ok",
            {
                "analytics_store": _analytics_store_raw(),
                "detail": "DuckDB bindings OK.",
            },
        )
    except Exception:
        return (
            False,
            "duckdb_failure",
            {
                "analytics_store": _analytics_store_raw(),
                "detail": "DuckDB probe failed.",
            },
        )
    finally:
        if eng is not None:
            try:
                eng.close()
            except Exception as exc:
                InternalMonitor.log_suppressed_error(
                    exc, context="duckdb_engine_close", domain="micro_dev_onboarding"
                )


def _lifecycle_state() -> Literal["uninitialized", "ready"]:
    """Aggregate gate for SPA: uninitialized until every *active* probe passes."""
    need_sqlite = ENGINE_KIND == "sqlite"
    need_duck = _analytics_uses_duckdb()

    if not need_sqlite and not need_duck:
        return "ready"

    if need_sqlite:
        ok, code, _ = _probe_sqlite_permissions()
        if not ok or code != "ok":
            return "uninitialized"

    if need_duck:
        ok, code, _ = _probe_duckdb_bindings()
        if not ok or code != "ok":
            return "uninitialized"

    return "ready"


class OnboardingCheckOut(BaseModel):
    id: str
    title: str
    description: str
    verify_path: str


class OnboardingStatusOut(BaseModel):
    lifecycle_state: Literal["uninitialized", "ready"]
    engine: str
    analytics_store: str
    checks: list[OnboardingCheckOut]


@router.get("/status", response_model=OnboardingStatusOut)
async def onboarding_status() -> OnboardingStatusOut:
    checks: list[OnboardingCheckOut] = []
    if ENGINE_KIND == "sqlite":
        p = _sqlite_database_path()
        checks.append(
            OnboardingCheckOut(
                id="sqlite_permissions",
                title="SQLite audit database",
                description=(
                    "Verify the decision-api SQLite file is on a writable volume and the process "
                    f"can open `{p}` for read/write."
                ),
                verify_path="/v1/micro-dev/onboarding/verify/sqlite",
            )
        )
    if _analytics_uses_duckdb():
        checks.append(
            OnboardingCheckOut(
                id="duckdb_bindings",
                title="DuckDB analytics bindings",
                description=(
                    "Verify the `duckdb` Python package is installed and can open the on-disk "
                    "analytics file (see `TARKA_ANALYTICS_DUCKDB_PATH`)."
                ),
                verify_path="/v1/micro-dev/onboarding/verify/duckdb",
            )
        )

    return OnboardingStatusOut(
        lifecycle_state=_lifecycle_state(),
        engine=ENGINE_KIND,
        analytics_store=_analytics_store_raw(),
        checks=checks,
    )


@router.get("/verify/sqlite")
async def verify_sqlite() -> dict[str, Any]:
    ok, code, detail = _probe_sqlite_permissions()
    if not ok:
        raise HTTPException(status_code=503, detail=_public_probe_detail(code, detail))
    return {
        "status": "ok",
        "check": "sqlite_permissions",
        "detail": _public_probe_detail(code, detail),
    }


@router.get("/verify/duckdb")
async def verify_duckdb() -> dict[str, Any]:
    ok, code, detail = _probe_duckdb_bindings()
    if not ok:
        raise HTTPException(status_code=503, detail=_public_probe_detail(code, detail))
    return {
        "status": "ok",
        "check": "duckdb_bindings",
        "detail": _public_probe_detail(code, detail),
    }
