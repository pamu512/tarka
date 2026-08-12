"""Brand / counterfeit connector (commercial brand-protection API).

No DIY crawl — configure base_url to the tenant's brand vendor gateway.
"""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from decision_api.vendors.base import (
    BaseVendorPlugin,
    NormalizedVendorSignal,
    VendorFetchContext,
    VendorTier,
)
from decision_api.vendors.exceptions import VendorUpstreamError


class BrandProtectionCredentials(BaseModel):
    api_key: str = Field(..., min_length=4, max_length=512)
    base_url: str = Field(..., min_length=8, max_length=512)

    @field_validator("base_url")
    @classmethod
    def strip_base(cls, v: str) -> str:
        return (v or "").strip().rstrip("/")


class BrandProtectionFeaturePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    listing_id: str = Field(..., min_length=1, max_length=256)
    seller_id: str | None = Field(default=None, max_length=256)
    title: str | None = Field(default=None, max_length=512)


class BrandProtectionVendorPlugin(BaseVendorPlugin):
    vendor_id = "brand_protection"
    tier = VendorTier.PREMIUM

    def __init__(self, credentials: BrandProtectionCredentials) -> None:
        super().__init__()
        self._creds = credentials

    def _credential_model(self) -> type[BaseModel]:
        return BrandProtectionCredentials

    def _validated_credentials(self) -> BrandProtectionCredentials:
        return self._creds

    def _build_get_url(self, features: dict[str, Any]) -> str:
        payload = BrandProtectionFeaturePayload.model_validate(features)
        lid = quote(payload.listing_id, safe="")
        return f"{self._creds.base_url}/v1/listings/{lid}/brand-risk"

    async def health_check(self, http: httpx.AsyncClient) -> dict[str, Any]:
        if not self._creds.api_key or not self._creds.base_url:
            raise VendorUpstreamError(
                vendor_id=self.vendor_id, message="brand_protection credentials missing"
            )
        return {
            "vendor_id": self.vendor_id,
            "ok": True,
            "mode": "credential_present",
            "note": "Commercial brand API — no in-repo crawler",
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
        hit = bool(
            data.get("hit")
            or data.get("match")
            or data.get("counterfeit")
            or data.get("brand_hit")
        )
        score = 78.0 if hit else 0.0
        reasons = (
            ["brand_protection:hit", "risk:counterfeit"]
            if hit
            else ["brand_protection:clear"]
        )
        return [
            NormalizedVendorSignal(
                vendor_id=self.vendor_id,
                score_0_100=score,
                reason_codes=reasons,
                raw_meta={
                    "http_status": http_status,
                    "brand": data.get("brand"),
                    "listing_id": data.get("listing_id"),
                },
            )
        ]

    async def fetch_signals(
        self, ctx: VendorFetchContext
    ) -> list[NormalizedVendorSignal]:
        BrandProtectionFeaturePayload.model_validate(ctx.features)
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
                message=f"brand_protection HTTP {r.status_code}",
                trace_id=ctx.trace_id,
                http_status=r.status_code,
            )
        return self._signals_from_body(r.text, r.status_code, ctx.trace_id)
