"""Processor webhook: signed POST binds dispute.outcome to the evaluate receipt.

Not a desk inbox. Outcome != FRAUD is still a y_label, not a second product.
"""

from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from decision_api.config import settings
from decision_api.gnn_loop.late_label import LateLabelError, bind_late_label
from decision_api.shared_path import ensure_services_shared_on_path

ensure_services_shared_on_path()
from tarka_request_signature import verify_signature  # noqa: E402

router = APIRouter(tags=["late-label"])


def _webhook_secret() -> str:
    return (
        os.environ.get("REQUEST_SIGNATURE_SECRET", "").strip()
        or (settings.request_signature_secret or "").strip()
    )


@router.post("/v1/webhooks/late-label")
async def late_label_webhook(request: Request) -> dict[str, Any]:
    raw = await request.body()
    secret = _webhook_secret()
    hdrs = {k: v for k, v in request.headers.items()}
    if not secret or not verify_signature(
        raw,
        hdrs,
        secret=secret,
        max_skew_seconds=int(settings.request_signature_max_skew_seconds),
    ):
        raise HTTPException(
            status_code=401, detail="invalid or missing request signature"
        )
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="invalid json") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid json")

    tenant_id = str(payload.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    dispute = payload.get("dispute") if isinstance(payload.get("dispute"), dict) else {}
    outcome = str(dispute.get("outcome") or "").strip()
    try:
        return bind_late_label(
            tenant_id,
            outcome=outcome,
            trace_id=str(payload.get("trace_id") or ""),
            evaluation_token=str(payload.get("evaluation_token") or ""),
        )
    except LateLabelError as exc:
        raise HTTPException(
            status_code=400,
            detail={"reason_code": exc.code, "message": str(exc)},
        ) from exc
