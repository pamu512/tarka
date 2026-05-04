"""Feature definitions (versioned) — metadata today; ClickHouse MV DDL generation for operators."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import sys
from pathlib import Path

_shared = Path(__file__).resolve().parents[3] / "shared"
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))
from auth_rbac import require_role  # noqa: E402

router = APIRouter(prefix="/v1/feature-store", tags=["feature-store"])

_lock = threading.Lock()
_STORE: dict[str, dict[str, Any]] = {}


class FeatureDefinition(BaseModel):
    name: str = Field(..., max_length=128)
    version: int = Field(default=1, ge=1, le=999)
    tenant_id: str = Field(..., max_length=128)
    aggregation: str = Field(..., description="count | sum | uniq")
    window_days: int = Field(default=7, ge=1, le=365)
    group_by: str = Field(..., max_length=64, description="e.g. entity_id, device_id")
    source_table: str = Field(default="fraud_decisions", max_length=128)


def _mv_sql(defn: FeatureDefinition) -> str:
    """Template AggregatingMergeTree MV (operators validate in staging)."""
    v = defn.version
    base = defn.name.replace("`", "")
    return f"""-- Feature {base}_v{v} (tenant-scoped); validate on staging before APPLY.
CREATE MATERIALIZED VIEW IF NOT EXISTS feature_{base}_v{v}
ENGINE = AggregatingMergeTree()
ORDER BY (tenant_id, {defn.group_by})
AS SELECT
  tenant_id,
  {defn.group_by},
  {defn.aggregation}(trace_id) AS metric_stub
FROM {defn.source_table}
WHERE tenant_id = '{{tenant_id:String}}'
GROUP BY tenant_id, {defn.group_by};
"""


@router.post("/definitions")
async def create_definition(
    body: FeatureDefinition,
    _user=Depends(require_role("admin")),
) -> dict[str, Any]:
    with _lock:
        key = f"{body.tenant_id}:{body.name}:v{body.version}"
        if key in _STORE:
            raise HTTPException(status_code=409, detail="definition_exists")
        rec = {
            "definition": body.model_dump(),
            "ddl": _mv_sql(body),
            "created_at": time.time(),
            "fingerprint": hashlib.sha256(json.dumps(body.model_dump(), sort_keys=True).encode()).hexdigest(),
        }
        _STORE[key] = rec
    return {"stored": True, "key": key, "clickhouse_mv_ddl": rec["ddl"]}


@router.get("/definitions")
async def list_definitions(
    tenant_id: str,
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    with _lock:
        items = [v for k, v in _STORE.items() if k.startswith(f"{tenant_id}:")]
    return {"items": items}
