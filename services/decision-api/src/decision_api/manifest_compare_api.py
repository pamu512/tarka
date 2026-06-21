"""Compare two EvidenceManifest traces (shadow vs production debugging)."""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from pathlib import Path
from typing import Any

from clickhouse_connect.driver.client import Client
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from decision_api.deps import get_clickhouse
from decision_api.manifest_compare_logic import build_full_manifest_comparison
from decision_api.manifest_visualize_api import (
    _fetch_manifest_bundle,
    _normalize_bool,
    _parse_trace_json,
)

_shared = Path(__file__).resolve().parents[3] / "shared"
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))
from auth_rbac import require_role  # noqa: E402

log = logging.getLogger("decision-api.manifest_compare")

router = APIRouter(prefix="/v1/compare", tags=["manifest-compare"])


class ManifestCompareRequest(BaseModel):
    """Pair of manifests to diff (e.g. production baseline vs shadow candidate)."""

    manifest_id_a: uuid.UUID = Field(
        ...,
        description="First manifest UUID (commonly production / champion).",
    )
    manifest_id_b: uuid.UUID = Field(
        ...,
        description="Second manifest UUID (commonly shadow / challenger).",
    )


def _metadata_final_bool(bundle: dict[str, Any]) -> bool:
    raw = bundle["final_decision"]
    if isinstance(raw, (int, float)):
        return bool(int(raw))
    return _normalize_bool(raw)


async def _fetch_bundle_labelled(
    ch: Client,
    manifest_id: uuid.UUID,
    role: str,
) -> dict[str, Any]:
    try:
        return await _fetch_manifest_bundle(ch, manifest_id)
    except HTTPException as exc:
        if exc.status_code == 404:
            detail = exc.detail
            base: dict[str, Any]
            if isinstance(detail, dict):
                base = dict(detail)
            else:
                base = {"message": str(detail)}
            base["missing_manifest_role"] = role
            base["manifest_id"] = str(manifest_id)
            raise HTTPException(status_code=404, detail=base) from exc
        log.warning("manifest fetch failed role=%s id=%s", role, manifest_id)
        raise


@router.post("/manifests")
async def compare_manifests(
    body: ManifestCompareRequest,
    ch: Client = Depends(get_clickhouse),
    _user=Depends(require_role("analyst")),
) -> dict[str, Any]:
    """Deep-diff execution paths and decoded intermediate state; pinpoints first divergent rule."""
    mid_a, mid_b = body.manifest_id_a, body.manifest_id_b

    bundle_a, bundle_b = await asyncio.gather(
        _fetch_bundle_labelled(ch, mid_a, "manifest_a"),
        _fetch_bundle_labelled(ch, mid_b, "manifest_b"),
    )

    steps_a = _parse_trace_json(bundle_a["trace_json"])
    steps_b = _parse_trace_json(bundle_b["trace_json"])

    final_a = _metadata_final_bool(bundle_a)
    final_b = _metadata_final_bool(bundle_b)

    return build_full_manifest_comparison(
        manifest_id_a=str(mid_a),
        manifest_id_b=str(mid_b),
        bundle_a=bundle_a,
        bundle_b=bundle_b,
        steps_a=steps_a,
        steps_b=steps_b,
        final_a=final_a,
        final_b=final_b,
    )
