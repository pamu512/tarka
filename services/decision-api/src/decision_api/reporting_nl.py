"""Natural-language → bounded ClickHouse SQL (Tier-1 reporting assist)."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from decision_api.config import settings

router = APIRouter(prefix="/v1/reporting", tags=["reporting"])

_ALLOWED = re.compile(r"^[a-zA-Z0-9_]+$")


class NaturalLanguageSqlRequest(BaseModel):
    tenant_id: str = Field(..., max_length=128)
    question: str = Field(..., max_length=2000, description="Analyst question; server maps to a safe template.")


def _allowed_tables() -> set[str]:
    raw = settings.nl_sql_allowed_tables or "fraud_decisions"
    return {t.strip() for t in raw.split(",") if t.strip() and _ALLOWED.match(t.strip())}


@router.post("/nl-to-sql")
async def nl_to_sql(body: NaturalLanguageSqlRequest) -> dict[str, Any]:
    """Return a parameterized ClickHouse template; execution is client-side or via BI."""
    allowed = _allowed_tables()
    if not allowed:
        raise HTTPException(status_code=503, detail="nl_sql_disabled")
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

    return {
        "tenant_id": body.tenant_id,
        "table": table,
        "sql_template": sql,
        "params": {"tenant_id": body.tenant_id},
        "notes": "Execute via ClickHouse HTTP client or BI; server does not run arbitrary SQL from raw NL.",
    }
