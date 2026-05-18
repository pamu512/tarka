"""HTTP routes for management-plane tooling (signal lineage)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from tarka_management.settings import ManagementSettings, get_settings
from tarka_management.signal_lineage import (
    LineageScanResult,
    filter_impact_for_signal,
    scan_yaml_rules_tree,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["signals"])


def _parse_excluded_globs(raw: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in (raw or "").split(",") if p.strip())


async def verify_optional_api_key(
    request: Request,
    settings: ManagementSettings = Depends(get_settings),
) -> None:
    expected = (settings.api_key or "").strip()
    if not expected:
        return
    incoming = (request.headers.get("x-api-key") or "").strip()
    if incoming != expected:
        raise HTTPException(
            status_code=401,
            detail={
                "reason_code": "MANAGEMENT_API_KEY_REQUIRED",
                "message": "Invalid or missing X-API-Key for management API.",
            },
        )


def _run_lineage_scan(settings: ManagementSettings) -> LineageScanResult:
    root = Path(settings.yaml_rules_root).expanduser()
    excluded = _parse_excluded_globs(settings.lineage_excluded_globs)
    try:
        return scan_yaml_rules_tree(
            root,
            excluded_globs=excluded,
            max_files=settings.lineage_max_files,
            max_file_bytes=settings.lineage_max_file_bytes,
        )
    except FileNotFoundError as exc:
        logger.warning("signal lineage rules root missing: %s", exc)
        raise HTTPException(
            status_code=503,
            detail={
                "reason_code": "LINEAGE_RULES_ROOT_UNAVAILABLE",
                "message": (
                    "YAML rules root does not exist or is not a directory. "
                    "Set TARKA_MANAGEMENT_YAML_RULES_ROOT to a mounted rules volume."
                ),
                "path": str(root),
                "cause": str(exc),
            },
        ) from exc


@router.get("/signals/impact")
async def signal_impact(
    request: Request,
    signal: str | None = Query(
        default=None,
        description="When set, return only rules referencing this signal name.",
        max_length=512,
    ),
    settings: ManagementSettings = Depends(get_settings),
    _auth: None = Depends(verify_optional_api_key),
) -> dict[str, Any]:
    """Crawl active compiler YAML rules and return signal ↔ rule impact mapping."""
    _ = request
    result = await anyio.to_thread.run_sync(_run_lineage_scan, settings)
    base: dict[str, Any] = {
        "generated_at": result.generated_at,
        "rules_root": result.rules_root,
        "rules": result.rules,
        "impact_by_signal": result.impact_by_signal,
        "files_scanned": result.files_scanned,
        "scan_summary": result.scan_summary,
    }
    if signal is not None and signal.strip() != "":
        base["filter"] = filter_impact_for_signal(result, signal)
    return base
