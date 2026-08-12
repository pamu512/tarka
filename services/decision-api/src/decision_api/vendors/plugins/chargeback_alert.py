"""Chargeback early-alert connector (Ethoca/Verifi-class).

Consortium card-network alerts — production connector, not DIY network graph.
Configure base_url to the tenant's Ethoca/Verifi (or equivalent) gateway.
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


class ChargebackAlertCredentials(BaseModel):
    api_key: str = Field(..., min_length=4, max_length=512)
    base_url: str = Field(..., min_length=8, max_length=512)

    @field_validator("base_url")
    @classmethod
    def strip_base(cls, v: str) -> str:
        return (v or "").strip().rstrip("/")


class ChargebackAlertFeaturePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    transaction_id: str = Field(..., min_length=1, max_length=256)
    card_bin: str | None = Field(default=None, max_length=8)
    amount: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=8)
    merchant_id: str | None = Field(default=None, max_length=128)


def _safe_txn_id(raw: str) -> str:
    safe = "".join(c for c in raw if c.isalnum() or c in "-_.:")[:256]
    if not safe:
        raise VendorUpstreamError(
            vendor_id="chargeback_alert", message="transaction_id invalid"
        )
    return safe


class ChargebackAlertVendorPlugin(BaseVendorPlugin):
    """GET ``{base}/v1/alerts/{transaction_id}`` → early-alert risk signals."""

    vendor_id = "chargeback_alert"
    tier = VendorTier.PREMIUM

    def __init__(self, credentials: ChargebackAlertCredentials) -> None:
        super().__init__()
        self._creds = credentials

    def _credential_model(self) -> type[BaseModel]:
        return ChargebackAlertCredentials

    def _validated_credentials(self) -> ChargebackAlertCredentials:
        return self._creds

    def _build_get_url(self, features: dict[str, Any]) -> str:
        payload = ChargebackAlertFeaturePayload.model_validate(features)
        return f"{self._creds.base_url}/v1/alerts/{_safe_txn_id(payload.transaction_id)}"

    async def health_check(self, http: httpx.AsyncClient) -> dict[str, Any]:
        if not self._creds.api_key or not self._creds.base_url:
            raise VendorUpstreamError(
                vendor_id=self.vendor_id, message="chargeback_alert credentials missing"
            )
        return {
            "vendor_id": self.vendor_id,
            "ok": True,
            "mode": "credential_present",
            "note": "Ethoca/Verifi-class gateway — LIVE after first successful fetch",
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
        if http_status == 404:
            return [
                NormalizedVendorSignal(
                    vendor_id=self.vendor_id,
                    score_0_100=0.0,
                    reason_codes=["chargeback_alert:no_alert"],
                    raw_meta={"http_status": http_status},
                )
            ]
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
        alert = bool(data.get("alert") or data.get("has_alert") or data.get("matched"))
        severity = str(data.get("severity") or data.get("risk_level") or "").lower()
        score = 0.0
        reasons = ["chargeback_alert:no_alert"]
        if alert:
            score = 72.0
            reasons = ["chargeback_alert:early_alert", "risk:friendly_fraud"]
            if severity in ("high", "critical"):
                score = 90.0
                reasons.append("chargeback_alert:high_severity")
            elif severity == "medium":
                score = 78.0
        return [
            NormalizedVendorSignal(
                vendor_id=self.vendor_id,
                score_0_100=score,
                reason_codes=reasons,
                raw_meta={
                    "http_status": http_status,
                    "alert_id": data.get("alert_id") or data.get("id"),
                    "severity": severity or None,
                    "consortium": data.get("source") or "ethoca_verifi_class",
                },
            )
        ]

    async def fetch_signals(
        self, ctx: VendorFetchContext
    ) -> list[NormalizedVendorSignal]:
        ChargebackAlertFeaturePayload.model_validate(ctx.features)
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
        ok = r.status_code < 400 or r.status_code == 404
        await self._persist_integration_audit(
            ctx,
            request_url=url,
            http_status=r.status_code,
            latency_ms=latency_ms,
            raw_response=r.text[:4096],
            outcome="ok" if ok else "upstream_error",
            error_detail=None if ok else f"HTTP {r.status_code}",
        )
        if not ok:
            raise VendorUpstreamError(
                vendor_id=self.vendor_id,
                message=f"chargeback_alert HTTP {r.status_code}",
                trace_id=ctx.trace_id,
                http_status=r.status_code,
            )
        return self._signals_from_body(r.text, r.status_code, ctx.trace_id)
