"""
Strict **IngestionSchema** for ``POST /ingest`` (browser SDK → Anumana).

Fail-closed: unknown fields, type coercion, and malformed fingerprints / IPs are rejected;
the HTTP layer maps validation failures to **400** (see orchestrator exception handler).
"""

from __future__ import annotations

import ipaddress
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_TENANT_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:@/+-]{0,255}$")
_SESSION_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$")
_B64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class TelemetryPacketV1(BaseModel):
    """Sealed telemetry blob (v1); integrity digest must be 64-char SHA-256 hex."""

    model_config = ConfigDict(extra="forbid", strict=True)

    v: Literal[1] = 1
    enc: str = Field(
        ...,
        min_length=8,
        max_length=65536,
        description="base64url(JSON) payload",
    )
    int: str = Field(
        ...,
        description="SHA-256 hex over enc",
        pattern=r"^[0-9a-fA-F]{64}$",
    )

    @field_validator("enc")
    @classmethod
    def _enc_charset(cls, v: str) -> str:
        if not _B64URL_RE.fullmatch(v):
            raise ValueError("enc must be base64url characters only")
        return v


class IngestionSchema(BaseModel):
    """
    Browser SDK envelope for ``POST /ingest``.

    * ``canvas_fingerprint`` / ``canvas_raster_digest_hex`` — lowercase/uppercase **hex** digests when set.
    * ``ip`` — syntactically valid IPv4 or IPv6 (normalized string form).
    * At least one of: non-null ``telemetry_packet``, ``canvas_fingerprint``, ``canvas_raster_digest_hex``.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    canvas_fingerprint: str | None = Field(
        default=None,
        description="Hex digest (e.g. canvas / composite fp); 32–512 nibbles.",
        pattern=r"^[0-9a-fA-F]{32,512}$",
    )
    canvas_raster_digest_hex: str | None = Field(
        default=None,
        description="SHA-256 hex of raster canvas digest.",
        pattern=r"^[0-9a-fA-F]{64}$",
    )
    ip: str | None = Field(default=None, max_length=64)
    tenant_id: str | None = Field(default=None, max_length=256)
    device_session_id: str | None = Field(default=None, max_length=128)
    telemetry_packet: TelemetryPacketV1 | None = None

    @field_validator("tenant_id")
    @classmethod
    def _tenant_normalize(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        if not s:
            return None
        if not _TENANT_RE.fullmatch(s):
            raise ValueError("tenant_id has invalid characters or shape")
        return s

    @field_validator("device_session_id")
    @classmethod
    def _session_normalize(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        if not s:
            return None
        if not _SESSION_RE.fullmatch(s):
            raise ValueError("device_session_id has invalid characters or shape")
        return s

    @field_validator("ip")
    @classmethod
    def _normalize_ip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        if not s:
            return None
        try:
            return str(ipaddress.ip_address(s))
        except ValueError as exc:
            raise ValueError("invalid ip address") from exc

    @model_validator(mode="after")
    def _at_least_one_signal(self) -> IngestionSchema:
        if self.telemetry_packet is not None:
            return self
        if self.canvas_fingerprint or self.canvas_raster_digest_hex:
            return self
        raise ValueError(
            "Provide telemetry_packet and/or canvas_fingerprint / canvas_raster_digest_hex",
        )


# Backward-compatible alias for internal imports.
BrowserTelemetryIngestBody = IngestionSchema
