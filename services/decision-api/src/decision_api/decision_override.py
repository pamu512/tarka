"""Analyst override: persist why as a y_label so the next evaluate can learn.

Does not claim the model already learned. Viewer stays 403.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from decision_api.shared_path import ensure_services_shared_on_path

ensure_services_shared_on_path()
from auth_rbac import require_role  # noqa: E402

from decision_api.label_join import y_label_from_ground_truth  # noqa: E402
from decision_api.y_label_store import merge_y_labels  # noqa: E402

router = APIRouter(prefix="/v1/calibration", tags=["calibration"])


class DecisionOverrideBody(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=128)
    trace_id: str = Field(..., min_length=1, max_length=128)
    entity_id: str = Field(..., min_length=1, max_length=512)
    y_label: str = Field(..., min_length=1, max_length=32)
    why: str = Field(..., min_length=1, max_length=2000)


@router.post("/y-labels/override")
async def override_decision_label(
    body: DecisionOverrideBody,
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    why = body.why.strip()
    if not why:
        raise HTTPException(status_code=400, detail="why is required")
    y = y_label_from_ground_truth(body.y_label)
    if y not in {"0", "1"}:
        raise HTTPException(
            status_code=400, detail="y_label must be FRAUD or LEGITIMATE"
        )
    store = merge_y_labels(
        body.tenant_id,
        by_trace={body.trace_id.strip(): y},
        by_entity={body.entity_id.strip(): y},
        why_by_trace={body.trace_id.strip(): why},
    )
    return {
        "ok": True,
        "schema_id": "tarka.decision_override/v1",
        "tenant_id": body.tenant_id,
        "trace_id": body.trace_id.strip(),
        "entity_id": body.entity_id.strip(),
        "y_label": y,
        "why": why,
        "learned": False,
        "store": {
            "trace_labels": store.get("trace_labels"),
            "entity_labels": store.get("entity_labels"),
        },
    }
