"""Natural-language → bounded ClickHouse SQL (Tier-1 reporting assist)."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from decision_api.config import settings

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/reporting", tags=["reporting"])

_ALLOWED = re.compile(r"^[a-zA-Z0-9_]+$")
_DANGEROUS_SQL = re.compile(
    r"\b(DROP|ALTER|INSERT|DELETE|TRUNCATE|ATTACH|DETACH|OPTIMIZE|SYSTEM|GRANT|REVOKE|EXECUTE)\b",
    re.IGNORECASE,
)
_FROM_JOIN_TABLE = re.compile(r"(?is)\b(?:from|join)\s+([a-zA-Z0-9_]+)\b")


class NaturalLanguageSqlRequest(BaseModel):
    tenant_id: str = Field(..., max_length=128)
    question: str = Field(..., max_length=2000, description="Analyst question; server maps to a safe template.")


def _allowed_tables() -> set[str]:
    raw = settings.nl_sql_allowed_tables or "fraud_decisions"
    return {t.strip() for t in raw.split(",") if t.strip() and _ALLOWED.match(t.strip())}


def _extract_sql_block(raw: str) -> str:
    text = raw.strip()
    fence = re.search(r"```(?:sql)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    return text


def _validate_generated_sql(sql: str, allowed: set[str]) -> None:
    s = sql.strip()
    if not s:
        raise ValueError("empty_sql")
    if ";" in s.rstrip().rstrip(";"):
        raise ValueError("multi_statement")
    if _DANGEROUS_SQL.search(s):
        raise ValueError("dangerous_keyword")
    head = s.lstrip().lower()
    if not (head.startswith("select") or head.startswith("with")):
        raise ValueError("not_select")
    for tbl in _FROM_JOIN_TABLE.findall(s):
        if tbl.lower() in ("select", "where", "on", "as", "and", "or", "not", "group", "order", "limit", "having"):
            continue
        if tbl not in allowed:
            raise ValueError(f"table_not_allowlisted:{tbl}")


async def _llm_generate_sql(question: str, allowed: set[str]) -> str:
    url = settings.reporting_nl_llm_url
    if not url:
        raise HTTPException(status_code=503, detail="nl_sql_llm_unconfigured")
    schema_hint = (
        "Allowed tables (ClickHouse): "
        + ", ".join(sorted(allowed))
        + ". Emit a single read-only SELECT (WITH is allowed) using placeholder "
        "{tenant_id:String} for tenant filter where appropriate. No DDL/DML."
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
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        log.warning("nl_sql unexpected LLM payload: %s", e)
        raise HTTPException(status_code=502, detail="nl_sql_llm_bad_response") from e
    if not isinstance(content, str):
        raise HTTPException(status_code=502, detail="nl_sql_llm_bad_response")
    return _extract_sql_block(content)


def _template_sql(body: NaturalLanguageSqlRequest, allowed: set[str]) -> tuple[str, str, dict[str, str]]:
    qlow = body.question.lower()
    table = "fraud_decisions" if "fraud_decisions" in allowed else next(iter(allowed))
    if "shadow" in qlow and "fraud_shadow_scores" in allowed:
        table = "fraud_shadow_scores"
    if "feature" in qlow and "fraud_features_offline" in allowed:
        table = "fraud_features_offline"
    if table not in allowed:
        raise HTTPException(status_code=400, detail={"error": "table_not_allowlisted", "allowed": sorted(allowed)})
    if any(k in qlow for k in ("count", "how many", "volume")):
        sql = f"SELECT count() AS c FROM {table} WHERE tenant_id = {{tenant_id:String}}"
    elif "deny" in qlow and "decision" in qlow:
        sql = f"SELECT decision, count() AS c FROM {table} WHERE tenant_id = {{tenant_id:String}} GROUP BY decision"
    else:
        sql = (
            f"SELECT trace_id, entity_id, decision, score, created_at FROM {table} "
            f"WHERE tenant_id = {{tenant_id:String}} ORDER BY created_at DESC LIMIT 500"
        )
    return sql, table, {"tenant_id": body.tenant_id}


@router.post("/nl-to-sql")
async def nl_to_sql(body: NaturalLanguageSqlRequest) -> dict[str, Any]:
    """Return a parameterized ClickHouse template; execution is client-side or via BI."""
    allowed = _allowed_tables()
    if not allowed:
        raise HTTPException(status_code=503, detail="nl_sql_disabled")

    if settings.reporting_nl_llm_url:
        sql = await _llm_generate_sql(body.question, allowed)
        try:
            _validate_generated_sql(sql, allowed)
        except ValueError as e:
            log.warning("nl_sql rejected LLM output: %s", e)
            raise HTTPException(status_code=400, detail={"error": "sql_validation_failed", "reason": str(e)}) from e
        tables_used = sorted({t for t in _FROM_JOIN_TABLE.findall(sql) if t in allowed})
        primary = tables_used[0] if len(tables_used) == 1 else (tables_used[0] if tables_used else next(iter(allowed)))
        return {
            "tenant_id": body.tenant_id,
            "table": primary,
            "sql_template": sql,
            "params": {"tenant_id": body.tenant_id},
            "notes": "LLM-generated; validated (no DDL/DML; allowlisted tables only). Execute via ClickHouse client or BI.",
            "source": "llm",
            "tables": tables_used,
        }

    sql, table, params = _template_sql(body, allowed)
    return {
        "tenant_id": body.tenant_id,
        "table": table,
        "sql_template": sql,
        "params": params,
        "notes": "Template fallback (set TARKA_REPORTING_NL_LLM_URL for LLM mode). Server does not run arbitrary SQL from raw NL.",
        "source": "template",
    }
