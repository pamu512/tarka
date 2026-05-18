"""Dependency health probes (Redis, ClickHouse, Rust surfaces) and Postgres for unified ``/health``.

``/v1/health/deep`` runs Redis + ClickHouse + tarka-py ingest gate (legacy shape).

``/health`` additionally probes Postgres, requires a ClickHouse INSERT probe when ClickHouse is
enabled, and verifies the Rust JSON rule engine extension when that backend is required.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import anyio
from fastapi import Request
from sqlalchemy import text
from starlette.responses import JSONResponse

from decision_api.config import settings
from decision_api.db import SessionLocal
from decision_api.deps import run_clickhouse_sync
from decision_api.redis_store import redis_tags

try:
    from tarka.decision import ingest_stats as tarka_ingest_stats
except Exception:  # pragma: no cover - exercised only when tarka wheel missing
    tarka_ingest_stats = None  # type: ignore[misc, assignment]

log = logging.getLogger("decision_api.health_deep")

_BUFFER_PRESSURE_PERCENT = 80  # must match tarka-py `ingest::BUFFER_PRESSURE_PERCENT`


def _now() -> float:
    return time.time()


def _validate_ch_insert_sql(sql: str) -> bool:
    s = sql.strip()
    if not s:
        return False
    return s.upper().startswith("INSERT ")


def _ingest_buffer_check(stats: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    cap = int(stats.get("capacity") or 0)
    inf = int(stats.get("in_flight") or 0)
    threshold_pct = int(stats.get("buffer_pressure_percent") or _BUFFER_PRESSURE_PERCENT)
    accepting = bool(stats.get("accepting_new_requests", True))

    detail: dict[str, Any] = {
        "capacity": cap,
        "in_flight": inf,
        "buffer_pressure_threshold_percent": threshold_pct,
        "accepting_new_requests": accepting,
        "token_refill_per_sec": stats.get("token_refill_per_sec"),
    }

    if cap == 0:
        detail["status"] = "skipped"
        detail["reason"] = "ingest gate disabled (TARKA_INGEST_BUFFER_CAPACITY=0)"
        return True, detail

    if not accepting:
        detail["status"] = "unhealthy"
        detail["reason"] = "engine not accepting new evaluations (shutdown or fatal gate state)"
        return False, detail

    # Mirror `IngestGate::try_enter` buffer-pressure predicate (Rust).
    if inf * 100 > cap * threshold_pct:
        detail["status"] = "unhealthy"
        detail["reason"] = (
            f"ingest buffer past high-water mark ({threshold_pct}%): "
            f"in_flight={inf} capacity={cap}"
        )
        return False, detail

    if inf >= cap:
        detail["status"] = "unhealthy"
        detail["reason"] = f"ingest buffer at capacity in_flight={inf} capacity={cap}"
        return False, detail

    detail["status"] = "healthy"
    detail["reason"] = "within ingest capacity and admission policy"
    return True, detail


async def _check_postgres() -> tuple[bool, dict[str, Any]]:
    """``SELECT 1`` via SQLAlchemy session (Postgres or SQLite)."""
    t0 = time.perf_counter()
    try:
        with anyio.fail_after(5.0):
            async with SessionLocal() as session:
                await session.execute(text("SELECT 1"))
    except TimeoutError:
        log.warning("health: postgres SELECT 1 timed out")
        return False, {
            "status": "unhealthy",
            "reason": "SELECT 1 timed out after 5s",
            "latency_ms": None,
        }
    except Exception as e:
        log.warning("health: postgres SELECT 1 failed: %s", e)
        return False, {
            "status": "unhealthy",
            "reason": f"SELECT 1 failed: {e}",
            "latency_ms": None,
        }
    latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
    return True, {
        "status": "healthy",
        "reason": "SELECT 1 ok",
        "latency_ms": latency_ms,
    }


def _check_rust_json_rules_engine() -> tuple[bool, dict[str, Any]]:
    """``tarka_rule_engine`` import + cheap native call when Rust backend is required."""
    mode = (settings.json_rules_engine or "auto").strip().lower()
    detail: dict[str, Any] = {"backend": mode}
    if mode == "python":
        detail["status"] = "skipped"
        detail["reason"] = "TARKA_JSON_RULES_ENGINE=python (Rust extension not required)"
        return True, detail
    try:
        import tarka_rule_engine as tre  # noqa: PLC0415
    except ImportError as e:
        if mode == "rust":
            detail["status"] = "unhealthy"
            detail["reason"] = f"tarka_rule_engine required but not importable: {e}"
            return False, detail
        detail["status"] = "skipped"
        detail["reason"] = f"tarka_rule_engine not installed (auto mode uses Python fallback): {e}"
        return True, detail
    try:
        tre.rust_engine_cache_stats()
    except Exception as e:
        log.warning("health: rust_engine_cache_stats failed: %s", e)
        detail["status"] = "unhealthy"
        detail["reason"] = f"rust_engine_cache_stats failed: {e}"
        return False, detail
    detail["status"] = "healthy"
    detail["reason"] = "Rust JSON rule engine extension responsive"
    return True, detail


async def _check_redis_ping() -> tuple[bool, dict[str, Any]]:
    redis_url = (settings.redis_url or "").strip()
    if not redis_url:
        return True, {
            "status": "skipped",
            "reason": "REDIS_URL not configured",
            "latency_ms": None,
            "max_latency_ms": settings.health_deep_redis_max_ping_ms,
        }
    if redis_tags._client is None:
        return False, {
            "status": "unhealthy",
            "reason": "Redis URL configured but client is not connected",
            "latency_ms": None,
            "max_latency_ms": settings.health_deep_redis_max_ping_ms,
        }
    t0 = time.perf_counter()
    try:
        with anyio.fail_after(5.0):
            await redis_tags._client.ping()
    except TimeoutError:
        log.warning("health: redis ping timed out")
        return False, {
            "status": "unhealthy",
            "reason": "PING timed out after 5s",
            "latency_ms": None,
            "max_latency_ms": settings.health_deep_redis_max_ping_ms,
        }
    except Exception as e:
        log.warning("health: redis ping failed: %s", e)
        return False, {
            "status": "unhealthy",
            "reason": f"PING failed: {e}",
            "latency_ms": None,
            "max_latency_ms": settings.health_deep_redis_max_ping_ms,
        }
    latency_ms = (time.perf_counter() - t0) * 1000.0
    max_ms = float(settings.health_deep_redis_max_ping_ms)
    ok = latency_ms <= max_ms
    detail = {
        "status": "healthy" if ok else "unhealthy",
        "reason": (
            "within latency budget"
            if ok
            else f"PING latency {latency_ms:.2f}ms exceeds max {max_ms}ms"
        ),
        "latency_ms": round(latency_ms, 3),
        "max_latency_ms": max_ms,
    }
    return ok, detail


async def _check_clickhouse(
    request: Request,
    *,
    require_write_probe: bool,
) -> tuple[bool, dict[str, Any]]:
    """Read ``SELECT 1``; optional INSERT probe (required when ``require_write_probe`` is True)."""
    ch_client = getattr(request.app.state, "clickhouse_client", None)
    ch_host = (settings.clickhouse_host or "").strip()
    if not ch_host or ch_client is None:
        return True, {
            "status": "skipped",
            "reason": "ClickHouse not configured or client unavailable",
            "read": None,
            "write": None,
        }

    read_ok = True
    read_detail: dict[str, Any]
    t0 = time.perf_counter()
    try:
        with anyio.fail_after(max(1.0, settings.clickhouse_statement_timeout_ms / 1000.0)):
            await run_clickhouse_sync(ch_client, lambda: ch_client.query("SELECT 1"))
    except TimeoutError:
        read_ok = False
        read_detail = {
            "status": "unhealthy",
            "reason": "SELECT 1 timed out",
            "latency_ms": None,
        }
        log.warning("health: ClickHouse SELECT 1 timed out")
    except Exception as e:
        read_ok = False
        read_detail = {
            "status": "unhealthy",
            "reason": f"SELECT 1 failed: {e}",
            "latency_ms": None,
        }
        log.warning("health: ClickHouse read failed: %s", e)
    else:
        read_detail = {
            "status": "healthy",
            "reason": "SELECT 1 ok",
            "latency_ms": round((time.perf_counter() - t0) * 1000.0, 3),
        }

    write_detail: dict[str, Any]
    insert_sql = (settings.clickhouse_health_probe_insert_sql or "").strip()

    if not read_ok:
        write_detail = {
            "status": "skipped",
            "reason": "write probe skipped because read probe failed",
            "latency_ms": None,
        }
    elif not insert_sql:
        if require_write_probe or settings.health_deep_require_clickhouse_write:
            write_detail = {
                "status": "unhealthy",
                "reason": (
                    "CLICKHOUSE_HEALTH_PROBE_INSERT_SQL is empty "
                    "(set a bounded INSERT for write probe)"
                ),
                "latency_ms": None,
            }
        else:
            write_detail = {
                "status": "skipped",
                "reason": (
                    "set CLICKHOUSE_HEALTH_PROBE_INSERT_SQL (bounded INSERT) "
                    "for write verification on /health"
                ),
                "latency_ms": None,
            }
    elif not _validate_ch_insert_sql(insert_sql):
        write_detail = {
            "status": "unhealthy",
            "reason": "CLICKHOUSE_HEALTH_PROBE_INSERT_SQL must start with INSERT (fail-closed)",
            "latency_ms": None,
        }
    else:
        tw = time.perf_counter()
        try:
            with anyio.fail_after(max(1.0, settings.clickhouse_statement_timeout_ms / 1000.0)):
                await run_clickhouse_sync(ch_client, lambda: ch_client.command(insert_sql))
        except TimeoutError:
            write_detail = {
                "status": "unhealthy",
                "reason": "WRITE probe timed out",
                "latency_ms": None,
            }
            log.warning("health: ClickHouse write probe timed out")
        except Exception as e:
            write_detail = {
                "status": "unhealthy",
                "reason": f"WRITE probe failed: {e}",
                "latency_ms": None,
            }
            log.warning("health: ClickHouse write probe failed: %s", e)
        else:
            write_detail = {
                "status": "healthy",
                "reason": "INSERT probe succeeded",
                "latency_ms": round((time.perf_counter() - tw) * 1000.0, 3),
            }

    write_st = write_detail.get("status")
    write_ok = write_st == "healthy" or (
        write_st == "skipped"
        and not require_write_probe
        and not settings.health_deep_require_clickhouse_write
    )
    branch_ok = read_ok and write_ok

    return branch_ok, {
        "status": "healthy" if branch_ok else "unhealthy",
        "read": read_detail,
        "write": write_detail,
    }


async def _check_rust_ingest() -> tuple[bool, dict[str, Any]]:
    if tarka_ingest_stats is None:
        log.warning("health: tarka ingest_stats not importable")
        return False, {
            "status": "unhealthy",
            "reason": "tarka-py ingest_stats unavailable (tarka package missing or broken)",
        }
    try:
        stats = tarka_ingest_stats()
    except Exception as e:
        log.warning("health: ingest_stats call failed: %s", e)
        return False, {
            "status": "unhealthy",
            "reason": f"failed to read ingest_stats from tarka-py: {e}",
        }
    ok_buf, detail_buf = _ingest_buffer_check(stats)
    return ok_buf, detail_buf


async def run_deep_health(request: Request) -> JSONResponse:
    """Run Redis + ClickHouse + tarka-py ingest probes; 200 when healthy, 503 otherwise."""
    checks: dict[str, Any] = {}
    overall_ok = True

    ok, d = await _check_redis_ping()
    checks["redis"] = d
    overall_ok &= ok

    ok, d = await _check_clickhouse(request, require_write_probe=False)
    checks["clickhouse"] = d
    overall_ok &= ok

    ok, d = await _check_rust_ingest()
    checks["rust_engine_ingest"] = d
    overall_ok &= ok

    payload: dict[str, Any] = {
        "status": "healthy" if overall_ok else "unhealthy",
        "service": "decision-api",
        "checks": checks,
        "timestamp": _now(),
    }

    if overall_ok:
        return JSONResponse(content=payload, status_code=200)

    return JSONResponse(content=payload, status_code=503)


async def run_unified_health(request: Request) -> JSONResponse:
    """Postgres + Redis + ClickHouse (read + write when enabled) + Rust engines; 503 if any fail."""
    checks: dict[str, Any] = {}
    overall_ok = True

    ok, d = await _check_postgres()
    checks["postgres"] = d
    overall_ok &= ok

    ok, d = await _check_redis_ping()
    checks["redis"] = d
    overall_ok &= ok

    ok, d = await _check_clickhouse(request, require_write_probe=True)
    checks["clickhouse"] = d
    overall_ok &= ok

    ing_ok, ing_detail = await _check_rust_ingest()
    jr_ok, jr_detail = _check_rust_json_rules_engine()
    rust_ok = ing_ok and jr_ok
    checks["rust_engine"] = {
        "status": "healthy" if rust_ok else "unhealthy",
        "json_rules_engine": jr_detail,
        "manifest_ingest": ing_detail,
    }
    overall_ok &= rust_ok

    payload: dict[str, Any] = {
        "status": "healthy" if overall_ok else "unhealthy",
        "service": "decision-api",
        "probe": "unified",
        "checks": checks,
        "timestamp": _now(),
    }

    if overall_ok:
        return JSONResponse(content=payload, status_code=200)

    return JSONResponse(content=payload, status_code=503)
