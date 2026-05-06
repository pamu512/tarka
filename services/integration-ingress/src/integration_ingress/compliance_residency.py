"""Data residency: audit rows, pre-socket guards, and admin residency vendor block matrix (integration plane)."""

from __future__ import annotations

import csv
import io
import json
import logging
import sys
import threading
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from integration_ingress.db import SessionLocal, get_session

_shared_auth = Path(__file__).resolve().parents[3] / "shared"
if str(_shared_auth) not in sys.path:
    sys.path.insert(0, str(_shared_auth))
from auth_rbac import require_role  # noqa: E402
from tarka_core.data_residency import (
    DataResidencyViolationError,
    assert_vendor_residency_allowed,
    coerce_residency,
)
from tarka_core.tenant_config import DataResidencyRegion

from integration_ingress.models import ComplianceResidencyAudit

log = logging.getLogger(__name__)

AUDIT_MAX_PAGE_SIZE = 200
AUDIT_DEFAULT_PAGE_SIZE = 25
AUDIT_CSV_EXPORT_MAX_ROWS = 100_000
AUDIT_CSV_BATCH = 2_000


def _parse_audit_datetime(param: str | None, *, field_name: str) -> datetime | None:
    if param is None or not str(param).strip():
        return None
    raw = str(param).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid {field_name}: {param}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _audit_where(
    *,
    tenant_id: str | None,
    tenant_id_prefix: str | None,
    vendor_key_contains: str | None,
    outcome: str | None,
    component: str | None,
    created_after: datetime | None,
    created_before: datetime | None,
) -> Any:
    m = ComplianceResidencyAudit
    clauses: list[Any] = []
    tid = (tenant_id or "").strip()
    if tid:
        clauses.append(m.tenant_id == tid[:128])
    else:
        pfx = (tenant_id_prefix or "").strip()
        if pfx:
            clauses.append(m.tenant_id.startswith(pfx[:128]))
    vk = (vendor_key_contains or "").strip()
    if vk:
        clauses.append(m.vendor_key.contains(vk[:128]))
    oc = (outcome or "").strip()
    if oc:
        clauses.append(m.outcome == oc[:32])
    comp = (component or "").strip()
    if comp:
        clauses.append(m.component == comp[:64])
    if created_after is not None:
        clauses.append(m.created_at >= created_after)
    if created_before is not None:
        clauses.append(m.created_at < created_before)
    if not clauses:
        return True
    return and_(*clauses)


def _audit_row_dict(r: ComplianceResidencyAudit) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "tenant_id": r.tenant_id,
        "component": r.component,
        "vendor_key": r.vendor_key,
        "tenant_region": r.tenant_region,
        "vendor_region": r.vendor_region,
        "outcome": r.outcome,
        "detail": r.detail,
        "request_url_preview": r.request_url_preview,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _csv_safe_cell(value: str | None) -> str:
    """Reduce CSV/formula injection when opened in spreadsheets."""
    s = "" if value is None else str(value)
    if s and s[0] in "=+-@":
        return "'" + s
    return s


# OSINT vendor_key → processing region (conservative: unknown third-party SaaS defaults to US).
OSINT_VENDOR_REGIONS: dict[str, DataResidencyRegion] = {
    "shodan": DataResidencyRegion.US,
    "abuseipdb": DataResidencyRegion.US,
    "greynoise": DataResidencyRegion.US,
    "ipinfo": DataResidencyRegion.US,
    "ip_api": DataResidencyRegion.EU,
    "emailrep": DataResidencyRegion.US,
    "gravatar": DataResidencyRegion.US,
    "hibp": DataResidencyRegion.EU,
    "numverify": DataResidencyRegion.US,
    "github": DataResidencyRegion.US,
    "rdap": DataResidencyRegion.GLOBAL,
}

# Additional third-party connectors shown in the residency matrix (non-OSINT egress).
CONNECTOR_VENDOR_REGIONS: dict[str, DataResidencyRegion] = {
    "stripe_radar": DataResidencyRegion.US,
    "jira": DataResidencyRegion.US,
    "salesforce": DataResidencyRegion.US,
    "complyadvantage": DataResidencyRegion.EU,
    "opensanctions": DataResidencyRegion.GLOBAL,
    "sift": DataResidencyRegion.US,
    "ip_quality_score": DataResidencyRegion.US,
}

_matrix_lock = threading.Lock()
# tenant_id -> set of vendor_key that are **administratively blocked** (pre-socket, before automatic residency rules).
_matrix_blocks: dict[str, set[str]] = {}
_matrix_store_path: Path | None = None


def _all_matrix_vendor_keys() -> list[str]:
    keys = set(OSINT_VENDOR_REGIONS) | set(CONNECTOR_VENDOR_REGIONS)
    return sorted(keys, key=lambda k: (k.lower(), k))


def vendor_processing_region(vendor_key: str) -> DataResidencyRegion:
    k = (vendor_key or "").strip()
    if k in OSINT_VENDOR_REGIONS:
        return OSINT_VENDOR_REGIONS[k]
    if k in CONNECTOR_VENDOR_REGIONS:
        return CONNECTOR_VENDOR_REGIONS[k]
    return DataResidencyRegion.US


def osint_vendor_region(vendor_key: str) -> DataResidencyRegion:
    return OSINT_VENDOR_REGIONS.get(vendor_key, DataResidencyRegion.US)


def _cell_key(tenant_id: str, vendor_key: str) -> str:
    return f"{tenant_id.strip()}::{vendor_key.strip()}"


def is_residency_matrix_blocked(tenant_id: str | None, vendor_key: str) -> bool:
    tid = (tenant_id or "").strip()
    vk = (vendor_key or "").strip()
    if not tid or not vk:
        return False
    with _matrix_lock:
        blocked = _matrix_blocks.get(tid)
        return bool(blocked and vk in blocked)


def _matrix_payload_from_memory() -> dict[str, list[str]]:
    with _matrix_lock:
        return {tid: sorted(ven) for tid, ven in sorted(_matrix_blocks.items()) if ven}


def _apply_matrix_payload(data: dict[str, Any]) -> None:
    global _matrix_blocks
    raw = data.get("blocks")
    if not isinstance(raw, dict):
        return
    next_map: dict[str, set[str]] = {}
    for tid, vlist in raw.items():
        t = str(tid).strip()[:128]
        if not t:
            continue
        if isinstance(vlist, list):
            vs = {str(v).strip()[:128] for v in vlist if str(v).strip()}
            if vs:
                next_map[t] = vs
    with _matrix_lock:
        _matrix_blocks = next_map


def _persist_matrix_to_disk() -> None:
    if _matrix_store_path is None:
        return
    path = _matrix_store_path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "blocks": _matrix_payload_from_memory()}
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        log.error("residency_matrix_persist_failed path=%s: %s", path, exc)


def init_residency_matrix_store(*, json_path: str | None) -> None:
    """Load optional JSON backing store (called from app lifespan)."""
    global _matrix_store_path, _matrix_blocks
    p = (json_path or "").strip()
    if not p:
        _matrix_store_path = None
        with _matrix_lock:
            _matrix_blocks = {}
        return
    path = Path(p).expanduser()
    _matrix_store_path = path
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            _apply_matrix_payload(data if isinstance(data, dict) else {})
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("residency_matrix_load_failed path=%s: %s", path, exc)
            with _matrix_lock:
                _matrix_blocks = {}
    else:
        with _matrix_lock:
            _matrix_blocks = {}


def set_residency_matrix_cell(*, tenant_id: str, vendor_key: str, blocked: bool) -> None:
    """Update one cell and persist (synchronous; called from FastAPI route)."""
    tid = tenant_id.strip()[:128]
    vk = vendor_key.strip()[:128]
    if not tid or not vk:
        raise ValueError("tenant_id and vendor_key are required")
    if vk not in _all_matrix_vendor_keys():
        raise ValueError(f"unknown vendor_key: {vk!r}")
    with _matrix_lock:
        s = _matrix_blocks.setdefault(tid, set())
        if blocked:
            s.add(vk)
        else:
            s.discard(vk)
            if not s:
                _matrix_blocks.pop(tid, None)
    _persist_matrix_to_disk()


async def record_residency_compliance_block(
    *,
    tenant_id: str | None,
    component: str,
    vendor_key: str,
    tenant_region: DataResidencyRegion,
    vendor_region: DataResidencyRegion,
    request_url_preview: str,
    detail: str,
    outcome: str = "compliance_block",
) -> None:
    """Persist an audit-plane row; failures are logged and swallowed."""
    tid = (tenant_id or "").strip() or "unknown"
    oc = (outcome or "compliance_block").strip()[:32] or "compliance_block"
    row = ComplianceResidencyAudit(
        id=uuid.uuid4(),
        tenant_id=tid[:128],
        component=component[:64],
        vendor_key=vendor_key[:128],
        tenant_region=tenant_region.value,
        vendor_region=vendor_region.value,
        outcome=oc,
        detail=detail[:8000],
        request_url_preview=request_url_preview[:2048],
    )
    try:
        async with SessionLocal() as session:
            session.add(row)
            await session.commit()
    except Exception as exc:  # pragma: no cover
        log.error(
            "compliance_residency_audit_write_failed tenant=%s vendor=%s: %s",
            tid,
            vendor_key,
            exc,
            extra={"audit_plane": "compliance", "event": "residency_audit_write_failed"},
        )


async def guard_osint_before_http(
    *,
    tenant_id: str | None,
    tenant_region: DataResidencyRegion | str | None,
    vendor_key: str,
    request_url: str,
) -> None:
    """Pre-socket residency check; on violation writes compliance audit then raises."""
    tid = (tenant_id or "").strip() or None
    vk = (vendor_key or "").strip() or "unknown"
    treg = coerce_residency(tenant_region)
    vreg = vendor_processing_region(vk)

    if tid and is_residency_matrix_blocked(tid, vk):
        await record_residency_compliance_block(
            tenant_id=tid,
            component="osint",
            vendor_key=vk,
            tenant_region=treg,
            vendor_region=vreg,
            request_url_preview=request_url,
            detail="Administrative block: tenant/vendor pair disabled in residency matrix (pre-socket).",
            outcome="policy_block",
        )
        log.warning(
            "data_residency_matrix_block vendor=%s tenant=%s",
            vk,
            tid,
            extra={
                "audit_plane": "compliance",
                "event": "data_residency_matrix_block",
                "vendor_key": vk,
            },
        )
        raise DataResidencyViolationError(
            tenant_region=treg,
            vendor_region=vreg,
            vendor_key=vk,
            message=f"tenant {tid!r} is blocked from vendor {vk!r} by residency matrix policy",
        )

    try:
        assert_vendor_residency_allowed(
            tenant_residency=treg,
            vendor_server_region=vreg,
            vendor_key=vk,
        )
    except DataResidencyViolationError as e:
        await record_residency_compliance_block(
            tenant_id=tid,
            component="osint",
            vendor_key=vk,
            tenant_region=treg,
            vendor_region=vreg,
            request_url_preview=request_url,
            detail=str(e),
            outcome="compliance_block",
        )
        log.warning(
            "data_residency_block vendor=%s tenant=%s",
            vk,
            tid or "unknown",
            extra={"audit_plane": "compliance", "event": "data_residency_block", "vendor_key": vk},
        )
        raise


# ── HTTP: residency matrix (tenant rows × vendor columns) ─────────────────

DEFAULT_TENANT_ROWS: list[dict[str, str]] = [
    {"id": "demo", "label": "Demo / sandbox", "residency_region": "GLOBAL"},
    {"id": "acme-corp", "label": "Acme Corp", "residency_region": "US"},
    {"id": "eu-financials", "label": "EU Financials Ltd", "residency_region": "EU"},
    {"id": "global-payments", "label": "Global Payments Co", "residency_region": "GLOBAL"},
    {"id": "us-retail", "label": "US Retail Group", "residency_region": "US"},
]


def _vendor_columns() -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for key in _all_matrix_vendor_keys():
        reg = vendor_processing_region(key)
        src = "osint" if key in OSINT_VENDOR_REGIONS else "connector"
        out.append(
            {
                "key": key,
                "label": key.replace("_", " ").title(),
                "processing_region": reg.value,
                "source": src,
            }
        )
    return out


def _matrix_response_dict() -> dict[str, Any]:
    cells: dict[str, bool] = {}
    with _matrix_lock:
        for tid, ven in _matrix_blocks.items():
            for vk in ven:
                cells[_cell_key(tid, vk)] = True
    return {
        "tenants": list(DEFAULT_TENANT_ROWS),
        "vendors": _vendor_columns(),
        "cells": cells,
        "legend": {
            "toggle_on": "Outbound blocked (pre-socket)",
            "toggle_off": "Not administratively blocked (automatic residency rules still apply)",
        },
    }


class ResidencyMatrixPutBody(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=128)
    vendor_key: str = Field(..., min_length=1, max_length=128)
    blocked: bool


residency_matrix_router = APIRouter(
    prefix="/v1/compliance/residency", tags=["compliance-residency"]
)


@residency_matrix_router.get("/matrix")
async def get_residency_matrix(_user=Depends(require_role("analyst"))):
    """Full matrix for UI: tenants, vendors (with processing region), and blocked cell keys ``tenant_id::vendor_key``."""
    return _matrix_response_dict()


@residency_matrix_router.put("/matrix")
async def put_residency_matrix_cell(
    body: ResidencyMatrixPutBody,
    _user=Depends(require_role("admin")),
):
    """Upsert one matrix cell (blocking rule). Requires admin — high-impact egress policy."""
    try:
        set_residency_matrix_cell(
            tenant_id=body.tenant_id, vendor_key=body.vendor_key, blocked=body.blocked
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, **_matrix_response_dict()}


@residency_matrix_router.get("/audit/export.csv")
async def export_compliance_residency_audit_csv(
    session: AsyncSession = Depends(get_session),
    _user=Depends(require_role("analyst")),
    tenant_id: str | None = Query(None, max_length=128),
    tenant_id_prefix: str | None = Query(None, max_length=128),
    vendor_key_contains: str | None = Query(None, max_length=128),
    outcome: str | None = Query(None, max_length=32),
    component: str | None = Query(None, max_length=64),
    created_after: str | None = Query(None),
    created_before: str | None = Query(None),
) -> StreamingResponse:
    """Stream CSV of audit rows matching filters (same semantics as ``GET /audit``; not paginated)."""
    ca = _parse_audit_datetime(created_after, field_name="created_after")
    cb = _parse_audit_datetime(created_before, field_name="created_before")
    where = _audit_where(
        tenant_id=tenant_id,
        tenant_id_prefix=tenant_id_prefix if not (tenant_id or "").strip() else None,
        vendor_key_contains=vendor_key_contains,
        outcome=outcome,
        component=component,
        created_after=ca,
        created_before=cb,
    )

    header = [
        "id",
        "tenant_id",
        "component",
        "vendor_key",
        "tenant_region",
        "vendor_region",
        "outcome",
        "detail",
        "request_url_preview",
        "created_at",
    ]

    async def row_chunks() -> AsyncIterator[bytes]:
        hbuf = io.StringIO()
        hwriter = csv.writer(hbuf, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        hwriter.writerow(header)
        yield hbuf.getvalue().encode("utf-8")

        offset = 0
        exported = 0
        while exported < AUDIT_CSV_EXPORT_MAX_ROWS:
            stmt = (
                select(ComplianceResidencyAudit)
                .where(where)
                .order_by(desc(ComplianceResidencyAudit.created_at))
                .offset(offset)
                .limit(AUDIT_CSV_BATCH)
            )
            batch = (await session.execute(stmt)).scalars().all()
            if not batch:
                break
            bbuf = io.StringIO()
            bwriter = csv.writer(bbuf, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
            for r in batch:
                if exported >= AUDIT_CSV_EXPORT_MAX_ROWS:
                    break
                bwriter.writerow(
                    [
                        str(r.id),
                        _csv_safe_cell(r.tenant_id),
                        _csv_safe_cell(r.component),
                        _csv_safe_cell(r.vendor_key),
                        _csv_safe_cell(r.tenant_region),
                        _csv_safe_cell(r.vendor_region),
                        _csv_safe_cell(r.outcome),
                        _csv_safe_cell(r.detail),
                        _csv_safe_cell(r.request_url_preview),
                        r.created_at.isoformat() if r.created_at else "",
                    ]
                )
                exported += 1
            yield bbuf.getvalue().encode("utf-8")
            offset += len(batch)
            if len(batch) < AUDIT_CSV_BATCH or exported >= AUDIT_CSV_EXPORT_MAX_ROWS:
                break

    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    fname = f"compliance_residency_audit_{stamp}.csv"
    headers = {
        "Content-Disposition": f'attachment; filename="{fname}"',
        "X-Export-Row-Cap": str(AUDIT_CSV_EXPORT_MAX_ROWS),
    }
    return StreamingResponse(
        row_chunks(),
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


@residency_matrix_router.get("/audit")
async def list_compliance_residency_audit(
    session: AsyncSession = Depends(get_session),
    _user=Depends(require_role("analyst")),
    page: int = Query(1, ge=1),
    page_size: int = Query(AUDIT_DEFAULT_PAGE_SIZE, ge=1, le=AUDIT_MAX_PAGE_SIZE),
    tenant_id: str | None = Query(None, max_length=128),
    tenant_id_prefix: str | None = Query(None, max_length=128),
    vendor_key_contains: str | None = Query(None, max_length=128),
    outcome: str | None = Query(None, max_length=32),
    component: str | None = Query(None, max_length=64),
    created_after: str | None = Query(
        None, description="ISO-8601 inclusive lower bound on created_at"
    ),
    created_before: str | None = Query(
        None, description="ISO-8601 exclusive upper bound on created_at"
    ),
) -> dict[str, Any]:
    """Paginated, filterable ``ComplianceResidencyAudit`` rows (read-only)."""
    ca = _parse_audit_datetime(created_after, field_name="created_after")
    cb = _parse_audit_datetime(created_before, field_name="created_before")
    where = _audit_where(
        tenant_id=tenant_id,
        tenant_id_prefix=tenant_id_prefix if not (tenant_id or "").strip() else None,
        vendor_key_contains=vendor_key_contains,
        outcome=outcome,
        component=component,
        created_after=ca,
        created_before=cb,
    )
    count_stmt = select(func.count()).select_from(ComplianceResidencyAudit).where(where)
    total = int((await session.execute(count_stmt)).scalar_one())
    offset = (page - 1) * page_size
    list_stmt = (
        select(ComplianceResidencyAudit)
        .where(where)
        .order_by(desc(ComplianceResidencyAudit.created_at))
        .offset(offset)
        .limit(page_size)
    )
    rows = (await session.execute(list_stmt)).scalars().all()
    return {
        "items": [_audit_row_dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": offset + len(rows) < total,
    }
