"""Incognia vendor plugin — delegates to ``adapters.biometrics.incognia``."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from decision_api.vendors.base import (
    BaseVendorPlugin,
    NormalizedVendorSignal,
    VendorFetchContext,
    VendorTier,
)
from decision_api.vendors.exceptions import VendorTimeoutError, VendorUpstreamError

_REPO_ROOT = Path(__file__).resolve().parents[6]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from adapters.biometrics.incognia.client import (  # noqa: E402
    IncogniaClient,
    IncogniaClientSettings,
)
from adapters.biometrics.incognia.exceptions import (  # noqa: E402
    IncogniaIntegrationError,
)
from adapters.biometrics.incognia.schemas import (  # noqa: E402
    PostTransactionRequestBody,
    incognia_transaction_assessment_to_tarka,
)


class IncogniaCredentials(BaseModel):
    client_id: str = Field(..., min_length=4, max_length=256)
    client_secret: str = Field(..., min_length=4, max_length=256)
    base_url: str = Field(default="https://api.incognia.com", max_length=256)

    @field_validator("base_url")
    @classmethod
    def strip_base(cls, v: str) -> str:
        return (v or "").strip().rstrip("/") or "https://api.incognia.com"


class IncogniaFeaturePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    account_id: str = Field(..., min_length=1, max_length=256)
    installation_id: str | None = Field(default=None, max_length=256)


class IncogniaVendorPlugin(BaseVendorPlugin):
    vendor_id = "incognia"
    tier = VendorTier.PREMIUM

    def __init__(self, credentials: IncogniaCredentials) -> None:
        super().__init__()
        self._creds = credentials

    def _credential_model(self) -> type[BaseModel]:
        return IncogniaCredentials

    def _validated_credentials(self) -> IncogniaCredentials:
        return self._creds

    def _build_get_url(self, features: dict[str, Any]) -> str:
        return f"{self._creds.base_url}/api/v2/authentication/transactions"

    def _client(self) -> IncogniaClient:
        return IncogniaClient(
            IncogniaClientSettings(
                client_id=self._creds.client_id,
                client_secret=self._creds.client_secret,
                api_base_url=self._creds.base_url,
            )
        )

    async def health_check(self, http: httpx.AsyncClient) -> dict[str, Any]:
        if not self._creds.client_id or not self._creds.client_secret:
            raise VendorUpstreamError(
                vendor_id=self.vendor_id, message="incognia credentials missing"
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
            message="incognia uses biometrics client; _parse_vendor_payload not used",
            trace_id=trace_id,
            http_status=http_status,
        )

    async def fetch_signals(
        self, ctx: VendorFetchContext
    ) -> list[NormalizedVendorSignal]:
        features = IncogniaFeaturePayload.model_validate(ctx.features)
        url = self._build_get_url(ctx.features)
        t0 = time.perf_counter()
        client = self._client()
        body = PostTransactionRequestBody(
            accountId=features.account_id,
            installationId=features.installation_id,
        )
        try:
            assessment = await client.post_transaction(body, evaluate_transaction=True)
            signal = incognia_transaction_assessment_to_tarka(
                assessment, api_base_url=self._creds.base_url
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
        except IncogniaIntegrationError as e:
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
            if "timeout" in str(e).lower():
                raise VendorTimeoutError(
                    vendor_id=self.vendor_id,
                    budget_ms=ctx.budget_ms,
                    trace_id=ctx.trace_id,
                ) from e
            raise VendorUpstreamError(
                vendor_id=self.vendor_id,
                message=str(e),
                trace_id=ctx.trace_id,
                http_status=http_status,
            ) from e
        finally:
            await client.aclose()
