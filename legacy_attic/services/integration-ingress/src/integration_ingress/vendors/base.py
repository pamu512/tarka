"""Abstract vendor surface for the integration plane (residency metadata for pre-flight checks)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from tarka_core.tenant_config import DataResidencyRegion


class BaseIntegrationVendor(ABC):
    """Every outbound integration vendor must declare where processing is expected to occur."""

    vendor_key: str = "unknown"

    @property
    @abstractmethod
    def server_region(self) -> DataResidencyRegion:
        """Vendor processing / data-at-rest region for residency routing (``GLOBAL`` if borderless)."""
