"""HTTP ingress for Ethoca/Verifi-class early-alert webhooks."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from decision_api.shared_path import ensure_services_shared_on_path

ensure_services_shared_on_path()
from auth_rbac import require_role  # noqa: E402

from decision_api.chargeback_alert_webhook import (  # noqa: E402
    normalize_chargeback_alert_payload,
)
from decision_api.chargeback_dispute_bridge import (  # noqa: E402
    maybe_open_dispute_from_alert,
)

router = APIRouter(prefix="/v1/webhooks/chargeback-alert", tags=["chargeback-alert"])


class ChargebackAlertBody(BaseModel):
    """Optional envelope; raw provider JSON also accepted via dict route."""

    tenant_id: str | None = Field(default=None, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
    open_dispute: bool = Field(
        default=True,
        description="When true and CASE_API_URL set, auto-open dispute (fail-soft).",
    )
    entity_id: str | None = Field(default=None, max_length=256)
    trace_id: str | None = Field(default=None, max_length=128)


@router.post("/{provider}")
async def chargeback_alert_webhook(
    provider: str,
    body: dict[str, Any],
    request: Request,
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Normalize consortium early-alert → features + optional case-api dispute."""
    inner = body.get("payload") if isinstance(body.get("payload"), dict) else body
    out = normalize_chargeback_alert_payload(
        provider, inner if isinstance(inner, dict) else {}
    )
    tenant_id = ""
    if isinstance(body.get("tenant_id"), str):
        tenant_id = body["tenant_id"].strip()
        out["tenant_id"] = tenant_id

    open_dispute = body.get("open_dispute", True)
    if open_dispute is False or not tenant_id:
        out["dispute_bridge"] = {
            "opened": False,
            "skipped_reason": "open_dispute_disabled_or_no_tenant"
            if not tenant_id
            else "open_dispute_false",
        }
        return out

    http: httpx.AsyncClient | None = getattr(request.app.state, "http", None)
    bridge = await maybe_open_dispute_from_alert(
        http=http,
        tenant_id=tenant_id,
        normalized=out,
        entity_id=str(body["entity_id"]) if body.get("entity_id") else None,
        trace_id=str(body["trace_id"]) if body.get("trace_id") else None,
    )
    out["dispute_bridge"] = bridge
    return out
