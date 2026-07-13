"""OpenSanctions Match API vendor plugin (callable catalog row)."""

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


class OpenSanctionsCredentials(BaseModel):
    api_key: str = Field(..., min_length=4, max_length=256)
    base_url: str = Field(default="https://api.opensanctions.org", max_length=256)
    dataset: str = Field(default="default", max_length=64)

    @field_validator("base_url")
    @classmethod
    def strip_base(cls, v: str) -> str:
        return (v or "").strip().rstrip("/") or "https://api.opensanctions.org"

    @field_validator("dataset")
    @classmethod
    def strip_dataset(cls, v: str) -> str:
        return (v or "").strip() or "default"


class OpenSanctionsFeaturePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    entity_name: str = Field(..., min_length=1, max_length=512)
    country: str | None = Field(default=None, max_length=64)
    birth_date: str | None = Field(default=None, max_length=32)


class OpenSanctionsVendorPlugin(BaseVendorPlugin):
    """POST ``/match/{dataset}`` → normalized sanctions risk signals."""

    vendor_id = "opensanctions"
    tier = VendorTier.STANDARD

    def __init__(self, credentials: OpenSanctionsCredentials) -> None:
        super().__init__()
        self._creds = credentials

    def _credential_model(self) -> type[BaseModel]:
        return OpenSanctionsCredentials

    def _validated_credentials(self) -> OpenSanctionsCredentials:
        return self._creds

    def _build_get_url(self, features: dict[str, Any]) -> str:
        ds = quote(self._creds.dataset, safe="")
        return f"{self._creds.base_url}/match/{ds}"

    async def health_check(self, http: httpx.AsyncClient) -> dict[str, Any]:
        if not self._creds.api_key:
            raise VendorUpstreamError(
                vendor_id=self.vendor_id, message="opensanctions api_key missing"
            )
        return {"vendor_id": self.vendor_id, "ok": True, "mode": "credential_present"}

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
            data = json.loads(response_text)
        except json.JSONDecodeError as e:
            raise VendorUpstreamError(
                vendor_id=self.vendor_id,
                message=f"invalid JSON: {e}",
                trace_id=trace_id,
                http_status=http_status,
            ) from e
        responses = data.get("responses") if isinstance(data, dict) else None
        if not isinstance(responses, dict):
            # Some Match API shapes return top-level results / matches.
            matches = []
            if isinstance(data, dict):
                matches = data.get("results") or data.get("matches") or []
            return self._from_matches(matches if isinstance(matches, list) else [])

        # Standard batch shape: responses.<query_id>.results
        all_matches: list[dict[str, Any]] = []
        for _qid, block in responses.items():
            if isinstance(block, dict):
                results = block.get("results") or []
                if isinstance(results, list):
                    all_matches.extend(r for r in results if isinstance(r, dict))
        return self._from_matches(all_matches)

    def _from_matches(self, matches: list[dict[str, Any]]) -> list[NormalizedVendorSignal]:
        if not matches:
            return [
                NormalizedVendorSignal(
                    vendor_id=self.vendor_id,
                    score_0_100=5.0,
                    reason_codes=["opensanctions:no_match"],
                    raw_meta={"match_count": 0},
                )
            ]
        best = max(
            (float(m.get("score") or m.get("match") or 0.0) for m in matches),
            default=0.0,
        )
        # OpenSanctions scores are typically 0–1; clamp if already 0–100.
        if best <= 1.0:
            score_0_100 = round(best * 100.0, 2)
        else:
            score_0_100 = round(min(100.0, best), 2)
        top = matches[0]
        caption = str(top.get("caption") or top.get("id") or "")[:256]
        reasons = ["opensanctions:match"]
        if score_0_100 >= 80.0:
            reasons.append("opensanctions:high_confidence")
        return [
            NormalizedVendorSignal(
                vendor_id=self.vendor_id,
                score_0_100=score_0_100,
                reason_codes=reasons,
                raw_meta={
                    "match_count": len(matches),
                    "best_score": best,
                    "top_caption": caption,
                    "top_id": str(top.get("id") or "")[:128],
                },
            )
        ]

    async def fetch_signals(self, ctx: VendorFetchContext) -> list[NormalizedVendorSignal]:
        features = OpenSanctionsFeaturePayload.model_validate(ctx.features)
        url = self._build_get_url(ctx.features)
        props: dict[str, Any] = {"name": [features.entity_name]}
        if features.country:
            props["country"] = [features.country]
        if features.birth_date:
            props["birthDate"] = [features.birth_date]
        body = {
            "queries": {
                "q1": {
                    "schema": "Person",
                    "properties": props,
                }
            }
        }
        t0 = time.perf_counter()
        try:
            r = await ctx.http.post(
                url,
                headers={
                    "Authorization": f"ApiKey {self._creds.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
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
                message=f"opensanctions HTTP {r.status_code}",
                trace_id=ctx.trace_id,
                http_status=r.status_code,
            )
        return self._signals_from_body(r.text, r.status_code, ctx.trace_id)
