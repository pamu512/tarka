"""Natural-language → bounded ClickHouse SQL (Tier-1 reporting assist)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
import sqlglot
from sqlglot import exp
from analytics.llm_validator import (
    AnalyticsSqlUnsafeError,
    ClickHouseSchemaRegistry,
    default_analytics_registry,
    validate_nl_sql_for_execution,
)
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from decision_api.config import settings

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/reporting", tags=["reporting"])

_ALLOWED = re.compile(r"^[a-zA-Z0-9_]+$")


class NaturalLanguageSqlRequest(BaseModel):
    tenant_id: str = Field(..., max_length=128)
    question: str = Field(
        ...,
        max_length=2000,
        description="Analyst question; answered only via configured LLM SQL generation.",
    )


def _allowed_tables() -> set[str]:
    raw = settings.nl_sql_allowed_tables or "fraud_decisions"
    return {
        t.strip() for t in raw.split(",") if t.strip() and _ALLOWED.match(t.strip())
    }


def _join_allowlist() -> set[frozenset[str]] | None:
    raw = (settings.nl_sql_allowed_joins or "").strip()
    if not raw:
        return None
    out: set[frozenset[str]] = set()
    for part in raw.split(","):
        part = part.strip()
        if "+" not in part:
            continue
        a, b = part.split("+", 1)
        a, b = a.strip(), b.strip()
        if a and b:
            out.add(frozenset({a, b}))
    return out or None


def _registry_subset(allowed: set[str]) -> ClickHouseSchemaRegistry:
    base = default_analytics_registry()
    unknown = sorted(t for t in allowed if not base.has_table(t))
    if unknown:
        raise ValueError(f"table_no_schema_in_registry:{unknown}")
    r = ClickHouseSchemaRegistry()
    for t in allowed:
        r.register_table(t, dict(base.tables[t]))
    return r


def _extract_sql_block(raw: str) -> str:
    text = raw.strip()
    fence = re.search(r"```(?:sql)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    return text


def _tables_in_sql(sql: str) -> list[str]:
    try:
        p = sqlglot.parse_one(sql, dialect="clickhouse")
    except Exception:
        return []
    return sorted({t.name for t in p.find_all(exp.Table) if t.name})


async def _llm_generate_sql(question: str, allowed: set[str]) -> str:
    url = (settings.reporting_nl_llm_url or "").strip()
    if not url:
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "LLM_ENGINE_OFFLINE",
                "message": "TARKA_REPORTING_NL_LLM_URL is not set.",
            },
        )
    schema_hint = (
        "Allowed tables (ClickHouse): "
        + ", ".join(sorted(allowed))
        + ". Emit a single read-only SELECT (WITH is allowed). "
        "You MUST include ``WHERE tenant_id = {tenant_id:String}`` (or AND the same predicate) on every "
        "query that reads those tables. No DDL/DML. Avoid JOIN unless instructed; JOIN is blocked unless "
        "operator allow-lists the edge in NL_SQL_ALLOWED_JOINS."
    )
    payload: dict[str, Any] = {
        "model": settings.reporting_nl_llm_model or "gpt-4o-mini",
        "temperature": 0,
        "messages": [
            {"role": "system", "content": schema_hint},
            {"role": "user", "content": question},
        ],
    }
    headers = {"Content-Type": "application/json"}
    if settings.reporting_nl_llm_api_key:
        headers["Authorization"] = f"Bearer {settings.reporting_nl_llm_api_key}"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(url, json=payload, headers=headers)
            try:
                r.raise_for_status()
            except httpx.HTTPStatusError as e:
                log.warning("nl_sql LLM HTTP error: %s", e)
                raise HTTPException(
                    status_code=503,
                    detail={
                        "reason_code": "LLM_REQUEST_FAILED",
                        "message": f"LLM provider returned HTTP {e.response.status_code}.",
                    },
                ) from e
            try:
                data = r.json()
            except json.JSONDecodeError as e:
                log.warning("nl_sql LLM non-JSON body: %s", e)
                raise HTTPException(
                    status_code=503,
                    detail={
                        "reason_code": "LLM_REQUEST_FAILED",
                        "message": "LLM provider returned a non-JSON response.",
                    },
                ) from e
    except httpx.TimeoutException as e:
        log.warning("nl_sql LLM timeout: %s", e)
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "LLM_ENGINE_OFFLINE",
                "message": "LLM request timed out.",
            },
        ) from e
    except httpx.ConnectError as e:
        log.warning("nl_sql LLM connection failed: %s", e)
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "LLM_ENGINE_OFFLINE",
                "message": "Could not connect to LLM provider.",
            },
        ) from e
    except httpx.RequestError as e:
        log.warning("nl_sql LLM request error: %s", e)
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "LLM_ENGINE_OFFLINE",
                "message": "LLM transport failed.",
            },
        ) from e
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        log.warning("nl_sql unexpected LLM payload: %s", e)
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "LLM_REQUEST_FAILED",
                "message": "LLM response did not contain a usable message payload.",
            },
        ) from e
    if not isinstance(content, str):
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "LLM_REQUEST_FAILED",
                "message": "LLM message content was not a string.",
            },
        )
    return _extract_sql_block(content)


@router.post("/nl-to-sql")
async def nl_to_sql(body: NaturalLanguageSqlRequest) -> dict[str, Any]:
    """Return validated, allowlisted ClickHouse SQL from the configured LLM; execution is client-side or via BI."""
    allowed = _allowed_tables()
    if not allowed:
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "NL_SQL_DISABLED",
                "message": "No allowlisted tables configured for NL→SQL (NL_SQL_ALLOWED_TABLES empty or invalid).",
            },
        )

    if not (settings.reporting_nl_llm_url or "").strip():
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "LLM_ENGINE_OFFLINE",
                "message": "TARKA_REPORTING_NL_LLM_URL is not set.",
            },
        )

    sql = await _llm_generate_sql(body.question, allowed)
    try:
        reg = _registry_subset(allowed)
    except ValueError as e:
        log.warning("nl_sql registry configuration error: %s", e)
        raise HTTPException(
            status_code=503,
            detail={"reason_code": "NL_SQL_DISABLED", "message": str(e)},
        ) from e

    try:
        hardened = validate_nl_sql_for_execution(
            sql,
            registry=reg,
            allowed_join_pairs=_join_allowlist(),
        )
    except AnalyticsSqlUnsafeError as e:
        log.warning("nl_sql unsafe after LLM: %s", e.errors)
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "ANALYTICS_QUERY_UNSAFE",
                "message": e.errors[0] if e.errors else "unsafe_sql",
                "errors": e.errors,
            },
        ) from e

    tables_used = [t for t in _tables_in_sql(hardened) if t in allowed]
    primary = tables_used[0] if tables_used else next(iter(allowed))
    return {
        "tenant_id": body.tenant_id,
        "table": primary,
        "sql_template": hardened,
        "params": {"tenant_id": body.tenant_id},
        "notes": (
            "LLM-generated; pre-execution lint (sqlglot), tenant_id bind enforced, "
            "SETTINGS max_execution_time=5s, JOINs blocked unless NL_SQL_ALLOWED_JOINS allow-lists the edge."
        ),
        "source": "llm",
        "tables": sorted(set(tables_used)),
    }
