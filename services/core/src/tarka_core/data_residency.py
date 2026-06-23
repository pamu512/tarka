"""Cross-border vendor guardrails (pre-socket, policy-only)."""

from __future__ import annotations

from typing import Any

from tarka_core.tenant_config import DataResidencyRegion


class DataResidencyViolationError(RuntimeError):
    """Raised before any outbound vendor HTTP when tenant residency forbids the vendor processing region."""

    reason_code = "DATA_RESIDENCY_VIOLATION"

    def __init__(
        self,
        *,
        tenant_region: DataResidencyRegion,
        vendor_region: DataResidencyRegion,
        vendor_key: str,
        message: str | None = None,
    ) -> None:
        self.tenant_region = tenant_region
        self.vendor_region = vendor_region
        self.vendor_key = vendor_key
        super().__init__(
            message
            or (
                f"tenant residency {tenant_region.value} cannot invoke vendor {vendor_key!r} "
                f"(vendor processing region {vendor_region.value})"
            )
        )

    def to_detail(self) -> dict[str, Any]:
        return {
            "reason_code": self.reason_code,
            "tenant_region": self.tenant_region.value,
            "vendor_region": self.vendor_region.value,
            "vendor_key": self.vendor_key,
            "message": str(self),
        }


def coerce_residency(value: DataResidencyRegion | str | None) -> DataResidencyRegion:
    if value is None or value == "":
        return DataResidencyRegion.GLOBAL
    if isinstance(value, DataResidencyRegion):
        return value
    s = str(value).strip().upper()
    if s in ("EU", "US", "GLOBAL"):
        return DataResidencyRegion(s)
    return DataResidencyRegion.GLOBAL


def assert_vendor_residency_allowed(
    *,
    tenant_residency: DataResidencyRegion | str | None,
    vendor_server_region: DataResidencyRegion | str,
    vendor_key: str,
) -> None:
    """Hard block: **EU** tenants must not call **US** processing-region vendors (pre-network).

    ``GLOBAL`` tenant or ``GLOBAL`` vendor region is always permitted. Symmetric US→EU is not blocked
    (policy targets EU data leakage to US OSINT).
    """
    t = coerce_residency(tenant_residency)
    v = coerce_residency(vendor_server_region)
    if t == DataResidencyRegion.GLOBAL or v == DataResidencyRegion.GLOBAL:
        return
    if t == DataResidencyRegion.EU and v == DataResidencyRegion.US:
        raise DataResidencyViolationError(tenant_region=t, vendor_region=v, vendor_key=vendor_key)
    return
