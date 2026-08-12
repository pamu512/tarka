"""Identity KYB/KYC connector (Sumsub/Persona/Onfido-class).

INFORM/DSA document verification — production connector; Tarka owns workflow
state in ``marketplace_kyb``.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from decision_api.vendors.base import (
    BaseVendorPlugin,
    NormalizedVendorSignal,
    VendorFetchContext,
    VendorTier,
)
from decision_api.vendors.exceptions import VendorUpstreamError


class IdentityKybCredentials(BaseModel):
    api_key: str = Field(..., min_length=4, max_length=512)
    base_url: str = Field(..., min_length=8, max_length=512)

    @field_validator("base_url")
    @classmethod
    def strip_base(cls, v: str) -> str:
        return (v or "").strip().rstrip("/")


class IdentityKybFeaturePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    applicant_id: str = Field(..., min_length=1, max_length=256)
    seller_id: str | None = Field(default=None, max_length=256)
    country: str | None = Field(default=None, max_length=64)


def _safe_id(raw: str) -> str:
    safe = "".join(c for c in raw if c.isalnum() or c in "-_.:")[:256]
    if not safe:
        raise VendorUpstreamError(
            vendor_id="identity_kyb", message="applicant_id invalid"
        )
    return safe


class IdentityKybVendorPlugin(BaseVendorPlugin):
    """GET ``{base}/v1/applicants/{id}/status`` → KYB verification signals."""

    vendor_id = "identity_kyb"
    tier = VendorTier.PREMIUM

    def __init__(self, credentials: IdentityKybCredentials) -> None:
        super().__init__()
        self._creds = credentials

    def _credential_model(self) -> type[BaseModel]:
        return IdentityKybCredentials

    def _validated_credentials(self) -> IdentityKybCredentials:
        return self._creds

    def _build_get_url(self, features: dict[str, Any]) -> str:
        payload = IdentityKybFeaturePayload.model_validate(features)
        return (
            f"{self._creds.base_url}/v1/applicants/"
            f"{_safe_id(payload.applicant_id)}/status"
        )

    async def health_check(self, http: httpx.AsyncClient) -> dict[str, Any]:
        if not self._creds.api_key or not self._creds.base_url:
            raise VendorUpstreamError(
                vendor_id=self.vendor_id, message="identity_kyb credentials missing"
            )
        return {
            "vendor_id": self.vendor_id,
            "ok": True,
            "mode": "credential_present",
            "note": "Sumsub/Persona/Onfido-class — LIVE after first successful fetch",
        }

    def _parse_vendor_payload(
        self,
        *,
        response_text: str,
        http_status: int,
        trace_id: Any,
    ) -> list[NormalizedVendorSignal]:
        return self._signals_from_body(response_text, http_status, trace_id)

    def _signals_from_body(
        self, response_text: str, http_status: int, trace_id: Any
    ) -> list[NormalizedVendorSignal]:
        try:
            data = json.loads(response_text) if response_text else {}
        except json.JSONDecodeError as e:
            raise VendorUpstreamError(
                vendor_id=self.vendor_id,
                message=f"invalid JSON: {e}",
                trace_id=trace_id,
                http_status=http_status,
            ) from e
        if not isinstance(data, dict):
            data = {}
        status = str(
            data.get("review_status")
            or data.get("status")
            or data.get("verification_status")
            or "unknown"
        ).lower()
        score = 40.0
        reasons = [f"identity_kyb:status:{status}"]
        if status in ("approved", "verified", "green", "completed"):
            score = 5.0
            reasons = ["identity_kyb:verified", "kyb:vendor_verified"]
        elif status in ("rejected", "declined", "red", "denied"):
            score = 85.0
            reasons = ["identity_kyb:rejected", "risk:kyb_rejected"]
        elif status in ("pending", "processing", "queued", "review"):
            score = 35.0
            reasons = ["identity_kyb:pending", "risk:kyb_pending"]
        elif status in ("resubmit", "retry", "needs_more_id"):
            score = 55.0
            reasons = ["identity_kyb:resubmit", "risk:kyb_unverified_high_volume"]
        return [
            NormalizedVendorSignal(
                vendor_id=self.vendor_id,
                score_0_100=score,
                reason_codes=reasons,
                raw_meta={
                    "http_status": http_status,
                    "vendor_status": status,
                    "applicant_id": data.get("applicant_id") or data.get("id"),
                },
            )
        ]

    async def fetch_signals(
        self, ctx: VendorFetchContext
    ) -> list[NormalizedVendorSignal]:
        IdentityKybFeaturePayload.model_validate(ctx.features)
        url = self._build_get_url(ctx.features)
        t0 = time.perf_counter()
        try:
            r = await ctx.http.get(
                url,
                headers={
                    "Authorization": f"Bearer {self._creds.api_key}",
                    "Accept": "application/json",
                },
                timeout=ctx.budget_ms / 1000.0,
            )
        except httpx.HTTPError as e:
            raise VendorUpstreamError(
                vendor_id=self.vendor_id, message=str(e), trace_id=ctx.trace_id
            ) from e
        latency_ms = (time.perf_counter() - t0) * 1000
        await self._persist_integration_audit(
            ctx,
            request_url=url,
            http_status=r.status_code,
            latency_ms=latency_ms,
            raw_response=r.text[:4096],
            outcome="ok" if r.status_code < 400 else "upstream_error",
            error_detail=None if r.status_code < 400 else f"HTTP {r.status_code}",
        )
        if r.status_code >= 400:
            raise VendorUpstreamError(
                vendor_id=self.vendor_id,
                message=f"identity_kyb HTTP {r.status_code}",
                trace_id=ctx.trace_id,
                http_status=r.status_code,
            )
        return self._signals_from_body(r.text, r.status_code, ctx.trace_id)
