"""Postgres audit rows for data-residency compliance blocks (integration plane, pre-socket)."""

from __future__ import annotations

import logging
import uuid

from integration_ingress.db import SessionLocal
from integration_ingress.models import ComplianceResidencyAudit
from tarka_core.data_residency import DataResidencyViolationError, assert_vendor_residency_allowed, coerce_residency
from tarka_core.tenant_config import DataResidencyRegion

log = logging.getLogger(__name__)

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


def osint_vendor_region(vendor_key: str) -> DataResidencyRegion:
    return OSINT_VENDOR_REGIONS.get(vendor_key, DataResidencyRegion.US)


async def record_residency_compliance_block(
    *,
    tenant_id: str | None,
    component: str,
    vendor_key: str,
    tenant_region: DataResidencyRegion,
    vendor_region: DataResidencyRegion,
    request_url_preview: str,
    detail: str,
) -> None:
    """Persist a **compliance_block** row (Audit Plane); failures are logged and swallowed."""
    tid = (tenant_id or "").strip() or "unknown"
    row = ComplianceResidencyAudit(
        id=uuid.uuid4(),
        tenant_id=tid[:128],
        component=component[:64],
        vendor_key=vendor_key[:128],
        tenant_region=tenant_region.value,
        vendor_region=vendor_region.value,
        outcome="compliance_block",
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
    treg = coerce_residency(tenant_region)
    vreg = osint_vendor_region(vendor_key)
    try:
        assert_vendor_residency_allowed(
            tenant_residency=treg,
            vendor_server_region=vreg,
            vendor_key=vendor_key,
        )
    except DataResidencyViolationError as e:
        await record_residency_compliance_block(
            tenant_id=tenant_id,
            component="osint",
            vendor_key=vendor_key,
            tenant_region=treg,
            vendor_region=vreg,
            request_url_preview=request_url,
            detail=str(e),
        )
        log.warning(
            "data_residency_block vendor=%s tenant=%s",
            vendor_key,
            (tenant_id or "").strip() or "unknown",
            extra={"audit_plane": "compliance", "event": "data_residency_block", "vendor_key": vendor_key},
        )
        raise
