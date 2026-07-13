"""Fingerprint Server API vendor plugin — delegates to ``adapters.biometrics.fingerprint``."""

from __future__ import annotations

import time
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from decision_api.vendors.adapters_path import ensure_adapters_on_path
from decision_api.vendors.base import (
    BaseVendorPlugin,
    NormalizedVendorSignal,
    VendorFetchContext,
    VendorTier,
)
from decision_api.vendors.exceptions import VendorUpstreamError

if ensure_adapters_on_path() is None:
    raise ImportError(
        "adapters/biometrics not found (monorepo adapters/ or /app/adapters in core-api image)"
    )

from adapters.biometrics.fingerprint.client import (  # noqa: E402
    FingerprintClient,
    FingerprintClientSettings,
)
from adapters.biometrics.fingerprint.exceptions import (  # noqa: E402
    FingerprintAuthenticationError,
    FingerprintCircuitOpenError,
    FingerprintMalformedPayloadError,
    FingerprintRateLimitError,
    FingerprintRequestNotFoundError,
    FingerprintUpstreamError,
)
from adapters.biometrics.fingerprint.schemas import (  # noqa: E402
    fingerprint_events_response_to_tarka,
)


class FingerprintCredentials(BaseModel):
    api_key: str = Field(..., min_length=8, max_length=256)
    base_url: str = Field(default="https://api.fpjs.io", max_length=256)

    @field_validator("base_url")
    @classmethod
    def strip_base(cls, v: str) -> str:
        return (v or "").strip().rstrip("/") or "https://api.fpjs.io"


class FingerprintFeaturePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    request_id: str = Field(..., min_length=8, max_length=128)


class FingerprintVendorPlugin(BaseVendorPlugin):
    vendor_id = "fingerprint"
    tier = VendorTier.PREMIUM

    def __init__(self, credentials: FingerprintCredentials) -> None:
        super().__init__()
        self._creds = credentials

    def _credential_model(self) -> type[BaseModel]:
        return FingerprintCredentials

    def _validated_credentials(self) -> FingerprintCredentials:
        return self._creds

    def _build_get_url(self, features: dict[str, Any]) -> str:
        payload = FingerprintFeaturePayload.model_validate(features)
        from urllib.parse import quote

        rid = quote(payload.request_id, safe="")
        return f"{self._creds.base_url}/events/{rid}"

    def _client(self) -> FingerprintClient:
        return FingerprintClient(
            FingerprintClientSettings(
                secret_api_key=self._creds.api_key,
                api_base_url=self._creds.base_url,
            )
        )

    async def health_check(self, http: httpx.AsyncClient) -> dict[str, Any]:
        if not self._creds.api_key:
            raise VendorUpstreamError(
                vendor_id=self.vendor_id, message="fingerprint api_key missing"
            )
        return {"vendor_id": self.vendor_id, "ok": True, "mode": "credential_present"}

    def _parse_vendor_payload(
        self,
        *,
        response_text: str,
        http_status: int,
        trace_id: Any,
    ) -> list[NormalizedVendorSignal]:
        raise VendorUpstreamError(
            vendor_id=self.vendor_id,
            message="fingerprint uses biometrics client; _parse_vendor_payload not used",
            trace_id=trace_id,
            http_status=http_status,
        )

    async def fetch_signals(
        self, ctx: VendorFetchContext
    ) -> list[NormalizedVendorSignal]:
        features = FingerprintFeaturePayload.model_validate(ctx.features)
        url = self._build_get_url(ctx.features)
        t0 = time.perf_counter()
        client = self._client()
        try:
            envelope = await client.get_event(features.request_id)
            signal = fingerprint_events_response_to_tarka(
                envelope, region_base_url=client.region_base_url
            )
            latency_ms = (time.perf_counter() - t0) * 1000
            await self._persist_integration_audit(
                ctx,
                request_url=url,
                http_status=200,
                latency_ms=latency_ms,
                raw_response=str(signal.model_dump(mode="json"))[:4096],
                outcome="ok",
                error_detail=None,
            )
            return [
                NormalizedVendorSignal(
                    vendor_id=self.vendor_id,
                    score_0_100=signal.score_0_100,
                    reason_codes=list(signal.reason_codes),
                    raw_meta={
                        "vendor": signal.vendor,
                        "provenance": signal.provenance.model_dump(mode="json"),
                        "features": signal.features,
                    },
                )
            ]
        except (
            FingerprintAuthenticationError,
            FingerprintRequestNotFoundError,
            FingerprintMalformedPayloadError,
            FingerprintRateLimitError,
            FingerprintCircuitOpenError,
            FingerprintUpstreamError,
        ) as e:
            latency_ms = (time.perf_counter() - t0) * 1000
            http_status = int(getattr(e, "http_status", None) or 502)
            await self._persist_integration_audit(
                ctx,
                request_url=url,
                http_status=http_status,
                latency_ms=latency_ms,
                raw_response=str(e)[:4096],
                outcome="upstream_error",
                error_detail=str(e)[:512],
            )
            raise VendorUpstreamError(
                vendor_id=self.vendor_id,
                message=str(e),
                trace_id=ctx.trace_id,
                http_status=http_status,
            ) from e
        finally:
            await client.aclose()
