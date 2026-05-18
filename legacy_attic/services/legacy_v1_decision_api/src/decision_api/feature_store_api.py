"""Feature definitions (versioned): Postgres metadata + ClickHouse MV execution (SR-01, SR-02)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import asyncpg
from clickhouse_connect.driver.client import Client
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

_shared = Path(__file__).resolve().parents[3] / "shared"
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))
from auth_rbac import require_role  # noqa: E402

from decision_api.config import settings  # noqa: E402
from decision_api.deps import get_clickhouse, get_pg_pool, run_clickhouse_sync  # noqa: E402
from decision_api.feature_store_engine import (  # noqa: E402
    FeatureMVInput,
    execute_feature_ddl,
    generate_clickhouse_ddl,
)

log = logging.getLogger("decision-api")

router = APIRouter(prefix="/v1/feature-store", tags=["feature-store"])

FEATURE_STORE_DDL_MAX_BYTES = 262_144

_DANGEROUS_DDL = re.compile(
    r"\b(SYSTEM|TRUNCATE|ATTACH\s+PART|DROP\s+DATABASE|EXCHANGE\s+TABLES|KILL\s+QUERY)\b",
    re.IGNORECASE,
)

_ALLOWED_CLICKHOUSE_DDL_PREFIXES: tuple[str, ...] = (
    "CREATE MATERIALIZED VIEW",
    "CREATE TABLE",
    "CREATE VIEW",
    "ALTER TABLE",
    "DROP TABLE",
    "DROP VIEW",
    "DROP DICTIONARY",
)


def _sql_leading_statement_upper(sql: str) -> str:
    """Strip block/line comments so the DDL gate sees the real leading keyword."""
    s = sql.strip()
    while "/*" in s:
        before, _, mid = s.partition("/*")
        _, _, after = mid.partition("*/")
        s = (before + after).strip()
    lines: list[str] = []
    for line in s.splitlines():
        q = line.split("--", 1)[0]
        q = q.split("#", 1)[0]
        lines.append(q)
    s = "\n".join(lines)
    return " ".join(s.split()).upper()


def _validate_admin_clickhouse_ddl(sql: str) -> str:
    """Reject empty, oversized, multi-statement, or disallowed DDL before hitting ClickHouse."""
    raw = sql.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty SQL body.")
    if len(raw.encode("utf-8")) > FEATURE_STORE_DDL_MAX_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"SQL exceeds maximum length ({FEATURE_STORE_DDL_MAX_BYTES} bytes).",
        )
    if _DANGEROUS_DDL.search(raw):
        raise HTTPException(
            status_code=400,
            detail="Statement class not allowed in this console (blocked patterns include SYSTEM, TRUNCATE, DROP DATABASE).",
        )
    single = raw.rstrip().rstrip(";").rstrip()
    if ";" in single:
        raise HTTPException(
            status_code=400,
            detail="Multiple statements are not allowed; send exactly one DDL statement.",
        )
    head = _sql_leading_statement_upper(raw)
    if not any(head.startswith(p) for p in _ALLOWED_CLICKHOUSE_DDL_PREFIXES):
        raise HTTPException(
            status_code=400,
            detail="SQL must begin with one of: "
            + ", ".join(_ALLOWED_CLICKHOUSE_DDL_PREFIXES),
        )
    return raw


class FeatureStoreDdlExecuteBody(BaseModel):
    sql: str = Field(..., max_length=FEATURE_STORE_DDL_MAX_BYTES)


class FeatureDefinitionPayload(BaseModel):
    name: str = Field(..., max_length=128)
    version: int = Field(default=1, ge=1, le=999)
    tenant_id: str = Field(..., max_length=128)
    aggregation: str = Field(..., description="count | sum | uniq")
    window_days: int = Field(default=7, ge=1, le=365)
    group_by: str = Field(..., max_length=64, description="e.g. entity_id, device_id")
    source_table: str = Field(default="fraud_decisions", max_length=128)


def _allowed_source_tables() -> set[str]:
    return {t.strip() for t in settings.nl_sql_allowed_tables.split(",") if t.strip()}


def _row_to_item(
    row: asyncpg.Record,
    *,
    include_ddl: bool,
) -> dict[str, Any]:
    definition = row["definition"]
    if isinstance(definition, str):
        definition = json.loads(definition)
    spec = FeatureMVInput(
        tenant_id=row["tenant_id"],
        name=row["name"],
        version=int(row["version"]),
        aggregation=str(definition.get("aggregation", "")),
        group_by=str(definition.get("group_by", "")),
        source_table=str(definition.get("source_table", "fraud_decisions")),
    )
    created_at: datetime | None = row["created_at"]
    updated_at: datetime | None = row["updated_at"]
    out: dict[str, Any] = {
        "id": str(row["id"]),
        "tenant_id": row["tenant_id"],
        "name": row["name"],
        "version": int(row["version"]),
        "definition": definition,
        "ddl_status": row["ddl_status"],
        "clickhouse_error": row["clickhouse_error"],
        "created_at": created_at.isoformat() if created_at else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
    }
    if include_ddl:
        try:
            out["clickhouse_mv_ddl"] = generate_clickhouse_ddl(spec)
        except ValueError as e:
            out["clickhouse_mv_ddl"] = None
            out["clickhouse_mv_ddl_note"] = str(e)
    return out


@router.post("/definitions")
async def create_definition(
    body: FeatureDefinitionPayload,
    pool: asyncpg.Pool = Depends(get_pg_pool),
    ch: Client = Depends(get_clickhouse),
    _user=Depends(require_role("admin")),
) -> dict[str, Any]:
    if body.source_table not in _allowed_source_tables():
        raise HTTPException(
            status_code=422,
            detail=f"source_table not in allowed list derived from NL_SQL_ALLOWED_TABLES: {sorted(_allowed_source_tables())}",
        )
    try:
        spec = FeatureMVInput(
            tenant_id=body.tenant_id,
            name=body.name,
            version=body.version,
            aggregation=body.aggregation,
            group_by=body.group_by,
            source_table=body.source_table,
        )
        ddl = generate_clickhouse_ddl(spec)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    definition_json = body.model_dump()
    fingerprint = hashlib.sha256(
        json.dumps(definition_json, sort_keys=True).encode()
    ).hexdigest()
    row_id = None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO feature_definitions (
                    tenant_id, name, version, definition, ddl_status, clickhouse_error, created_at, updated_at
                )
                VALUES ($1, $2, $3, $4::jsonb, 'pending', NULL, now(), now())
                RETURNING id, tenant_id, name, version, definition, ddl_status, clickhouse_error, created_at, updated_at
                """,
                body.tenant_id,
                body.name,
                body.version,
                json.dumps(definition_json),
            )
            row_id = row["id"]
    except asyncpg.UniqueViolationError as e:
        raise HTTPException(status_code=409, detail="definition_exists") from e

    assert row_id is not None

    try:
        await execute_feature_ddl(ch, ddl)
    except Exception as e:
        err_msg = str(e)[:8192]
        log.warning(
            "ClickHouse DDL execution failed for feature_definitions id=%s: %s",
            row_id,
            err_msg,
        )
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE feature_definitions
                SET ddl_status = 'failed', clickhouse_error = $1, updated_at = now()
                WHERE id = $2::uuid
                """,
                err_msg,
                row_id,
            )
            final = await conn.fetchrow(
                "SELECT id, tenant_id, name, version, definition, ddl_status, clickhouse_error, created_at, updated_at "
                "FROM feature_definitions WHERE id = $1::uuid",
                row_id,
            )
        assert final is not None
        out = _row_to_item(final, include_ddl=True)
        out["fingerprint"] = fingerprint
        out["clickhouse_execution"] = "failed"
        return out

    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE feature_definitions
            SET ddl_status = 'applied', clickhouse_error = NULL, updated_at = now()
            WHERE id = $1::uuid
            """,
            row_id,
        )
        final = await conn.fetchrow(
            "SELECT id, tenant_id, name, version, definition, ddl_status, clickhouse_error, created_at, updated_at "
            "FROM feature_definitions WHERE id = $1::uuid",
            row_id,
        )
    assert final is not None
    out = _row_to_item(final, include_ddl=True)
    out["fingerprint"] = fingerprint
    out["clickhouse_execution"] = "applied"
    return out


@router.get("/definitions")
async def list_definitions(
    tenant_id: str,
    pool: asyncpg.Pool = Depends(get_pg_pool),
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, tenant_id, name, version, definition, ddl_status, clickhouse_error, created_at, updated_at
            FROM feature_definitions
            WHERE tenant_id = $1
            ORDER BY created_at DESC
            """,
            tenant_id,
        )
    items = [_row_to_item(r, include_ddl=True) for r in rows]
    return {"items": items, "tenant_id": tenant_id}


@router.post("/ddl/execute")
async def execute_feature_store_ddl(
    body: FeatureStoreDdlExecuteBody,
    ch: Client = Depends(get_clickhouse),
    _user=Depends(require_role("admin")),
) -> dict[str, Any]:
    """Run a single gated ClickHouse DDL statement; returns ClickHouse driver errors verbatim in HTTP 422."""
    ddl = _validate_admin_clickhouse_ddl(body.sql)

    def _run() -> None:
        ch.command(ddl)

    try:
        await run_clickhouse_sync(ch, _run)
    except Exception as e:
        msg = str(e).strip() or repr(e)
        log.warning("feature-store admin ddl failed: %s", msg[:500])
        raise HTTPException(status_code=422, detail=msg[:65536]) from e
    return {"ok": True, "executed": True}


# Backward-compatible name for callers expecting the Pydantic request model symbol.
FeatureDefinition = FeatureDefinitionPayload
