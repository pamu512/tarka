"""
Unified browser SDK signal envelope with shorthand JSON keys (aliases) for bandwidth.

Validation detects **inconsistent** hardware/network/session/behavior combinations and rejects payloads
that look **tampered** (e.g. desktop RAM on an ancient phone UA) or logically impossible (headless +
non-zero mouse velocity).
"""

from __future__ import annotations

import re
from datetime import datetime
from ipaddress import IPv4Address
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _looks_like_iphone4_era_ua(user_agent: str) -> bool:
    """Heuristic: UA strings typical of iPhone 4 / iOS 4-era Safari (no multi‑GB RAM)."""
    u = user_agent.lower()
    if "iphone os 3" in u or "iphone os 4" in u:
        return True
    if re.search(r"iphone\s*4[,;\)]", u):
        return True
    if "cpu iphone os 4" in u:
        return True
    return False


class UnifiedSignalSchema(BaseModel):
    """
    Full descriptive names internally; wire JSON uses short aliases from the Browser SDK.

    ``device_memory`` follows the ``navigator.deviceMemory`` convention (approximate **gigabytes** as
    an integer, e.g. ``8`` for ~8 GB class hardware).
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    canvas_hash: str = Field(..., alias="ch")
    webgl_vendor: str = Field(..., alias="wv")
    device_memory: int = Field(..., alias="dm", ge=0)
    client_ip: IPv4Address = Field(..., alias="ip")
    is_proxy: bool = Field(..., alias="px")
    user_agent: str = Field(..., alias="ua")
    session_id: UUID = Field(..., alias="sid")
    timestamp: datetime = Field(..., alias="ts")
    sdk_version: str = Field(..., alias="sv")
    mouse_velocity: float = Field(..., alias="mv")
    touch_points: int = Field(..., alias="tp", ge=0)
    is_headless: bool = Field(..., alias="hh")
    session_nonce: str | None = Field(
        default=None,
        alias="n",
        max_length=256,
        description="Server-issued nonce (page load); not included in transit-integrity canonical JSON.",
    )
    client_integrity_hash: str | None = Field(
        default=None,
        alias="ih",
        description="SHA-256 hex over canonical JSON (all fields except n/ih) + '|' + session_nonce.",
        pattern=r"^[0-9a-fA-F]{64}$",
    )
    geo_country_code: str | None = Field(
        default=None,
        alias="gc",
        max_length=2,
        description="ISO 3166-1 alpha-2 from local GeoIP (server-enriched).",
    )
    geo_city_name: str | None = Field(
        default=None,
        alias="gct",
        max_length=256,
        description="City name from local GeoIP (server-enriched).",
    )

    @field_validator("session_nonce")
    @classmethod
    def _strip_nonce(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    @field_validator("geo_country_code")
    @classmethod
    def _geo_country_upper(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = str(v).strip().upper()
        return s or None

    @model_validator(mode="after")
    def _nonce_and_hash_paired(self) -> UnifiedSignalSchema:
        has_n = self.session_nonce is not None
        has_ih = self.client_integrity_hash is not None
        if has_n ^ has_ih:
            raise ValueError("session_nonce (n) and client_integrity_hash (ih) must both be set or both omitted")
        return self

    @model_validator(mode="after")
    def inconsistent_signals(self) -> UnifiedSignalSchema:
        """
        Cross-field checks for spoofed or contradictory client reports.

        Raises ``ValueError`` so Pydantic surfaces a ``ValidationError`` (payload treated as invalid).
        """
        ua = self.user_agent
        mem = self.device_memory

        if _looks_like_iphone4_era_ua(ua) and mem >= 4:
            raise ValueError(
                "Inconsistent signals (TAMPERED): device_memory is incompatible with user_agent "
                "(legacy iPhone-class UA cannot match multi‑GB deviceMemory)",
            )

        if self.is_headless and self.mouse_velocity > 0:
            raise ValueError(
                "Inconsistent signals: is_headless is true but mouse_velocity is greater than zero",
            )

        return self
