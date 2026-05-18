"""
Local **GeoLite2 / MaxMind** MMDB lookup (entire DB held in memory via ``geoip2`` + ``BytesIO``).

Env:

* ``SIGNAL_GEOIP_MMDB`` or ``GEOIP_MMDB_PATH`` — path to ``GeoLite2-City.mmdb`` (or compatible).

When unset or missing, :class:`NullGeoEnrichmentProvider` is used (no-op, O(1)).
"""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from typing import Any

from tarka_v2_core.schemas.ingestion import UnifiedSignalSchema

logger = logging.getLogger(__name__)

try:
    from geoip2.errors import AddressNotFoundError
except ImportError:  # pragma: no cover - tests may construct LocalGeoIpProvider with a mock reader

    class AddressNotFoundError(Exception):
        """Placeholder when geoip2 is not installed."""


class GeoEnrichmentProvider:
    """Sync enrichment of :class:`UnifiedSignalSchema` with ``geo_country_code`` / ``geo_city_name``."""

    def enrich_unified_signal(self, body: UnifiedSignalSchema) -> UnifiedSignalSchema:
        raise NotImplementedError


class NullGeoEnrichmentProvider(GeoEnrichmentProvider):
    def enrich_unified_signal(self, body: UnifiedSignalSchema) -> UnifiedSignalSchema:
        return body


class LocalGeoIpProvider(GeoEnrichmentProvider):
    """In-memory MMDB reader (file bytes loaded at construction)."""

    __slots__ = ("_reader",)

    def __init__(self, reader: Any) -> None:
        self._reader = reader

    def close(self) -> None:
        if self._reader is not None:
            try:
                self._reader.close()
            except Exception:
                logger.exception("geo_local_reader_close_failed")
            self._reader = None

    @staticmethod
    def from_path(path: Path | None) -> GeoEnrichmentProvider:
        if path is None or not path.is_file():
            return NullGeoEnrichmentProvider()
        try:
            from geoip2.database import Reader
        except ImportError:
            logger.warning("geoip2_not_installed_skip_mmdb path=%s", path)
            return NullGeoEnrichmentProvider()

        buf = path.read_bytes()
        reader = Reader(io.BytesIO(buf))
        logger.info("geo_local_mmdb_loaded path=%s bytes=%s", path, len(buf))
        return LocalGeoIpProvider(reader)

    def lookup(self, ip: str) -> tuple[str | None, str | None]:
        try:
            rec = self._reader.city(ip)
        except (AddressNotFoundError, ValueError, OSError):
            return None, None
        cc = rec.country.iso_code
        city = rec.city.name
        return (str(cc).upper() if cc else None, city)

    def enrich_unified_signal(self, body: UnifiedSignalSchema) -> UnifiedSignalSchema:
        cc, city = self.lookup(str(body.client_ip))
        return body.model_copy(update={"geo_country_code": cc, "geo_city_name": city})


def build_geo_provider_from_env() -> GeoEnrichmentProvider:
    raw = (os.environ.get("SIGNAL_GEOIP_MMDB") or os.environ.get("GEOIP_MMDB_PATH") or "").strip()
    path = Path(raw) if raw else None
    return LocalGeoIpProvider.from_path(path)
