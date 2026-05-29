"""ip-api.com geolocation connector (free HTTP tier or optional Pro HTTPS).

Reference plugin: validates input with Pydantic, maps JSON to ``NormalizedVendorSignal``,
and relies on :class:`BaseVendorPlugin` for retries, timeouts, and Postgres audit.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote, urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from decision_api.vendors.base import (
    BaseVendorPlugin,
    NormalizedVendorSignal,
    VendorTier,
)
from decision_api.vendors.exceptions import VendorUpstreamError


class IpApiVendorCredentials(BaseModel):
    """Vendor credentials (optional Pro key). Free tier uses cleartext HTTP per ip-api policy."""

    api_key: str | None = Field(default=None, max_length=256)
    base_url: str = Field(
        default="http://ip-api.com",
        max_length=256,
        description="Origin for JSON API (free tier defaults to http://ip-api.com).",
    )

    @field_validator("base_url")
    @classmethod
    def strip_base(cls, v: str) -> str:
        s = (v or "").strip().rstrip("/")
        if not s:
            raise ValueError("base_url must be non-empty")
        return s


class IpApiFeaturePayload(BaseModel):
    """Strict feature slice required for a lookup (rejects unknown keys unless extra is needed)."""

    model_config = ConfigDict(extra="ignore")

    ip: str = Field(..., min_length=3, max_length=128)

    @field_validator("ip")
    @classmethod
    def must_be_ip(cls, v: str) -> str:
        from ipaddress import ip_address

        ip_address(v.strip())
        return v.strip()


class IpApiVendorPlugin(BaseVendorPlugin):
    """Real OSINT adapter: ip-api JSON field bundle + coarse risk score from hosting/proxy heuristics."""

    vendor_id = "ip_api"
    tier = VendorTier.CHEAP

    def __init__(self, credentials: IpApiVendorCredentials) -> None:
        super().__init__()
        self._creds = credentials

    def _credential_model(self) -> type[BaseModel]:
        return IpApiVendorCredentials

    def _validated_credentials(self) -> IpApiVendorCredentials:
        return self._creds

    def _build_get_url(self, features: dict[str, Any]) -> str:
        payload = IpApiFeaturePayload.model_validate(features)
        ip_enc = quote(payload.ip, safe="")
        fields = "status,message,country,countryCode,region,city,lat,lon,isp,org,as,proxy,hosting,query,mobile"
        if self._creds.api_key:
            q = urlencode({"fields": fields, "key": self._creds.api_key})
            return f"https://pro.ip-api.com/json/{ip_enc}?{q}"
        q = urlencode({"fields": fields})
        return f"{self._creds.base_url}/json/{ip_enc}?{q}"

    async def health_check(self, http: httpx.AsyncClient) -> dict[str, Any]:
        """Lightweight reachability probe (fixed public resolver target)."""
        url = self._build_get_url({"ip": "1.1.1.1"})
        timeout = httpx.Timeout(3.0, connect=2.0)
        resp = await http.get(url, follow_redirects=True, timeout=timeout)
        body = resp.text
        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            raise VendorUpstreamError(
                vendor_id=self.vendor_id,
                message=f"health_check JSON decode failed: {e}",
                http_status=resp.status_code,
            ) from e
        if data.get("status") != "success":
            raise VendorUpstreamError(
                vendor_id=self.vendor_id,
                message=f"health_check upstream status={data.get('status')!r}: {data.get('message')!r}",
                http_status=resp.status_code,
            )
        return {
            "vendor_id": self.vendor_id,
            "ok": True,
            "probe_query": data.get("query"),
        }

    def _parse_vendor_payload(
        self,
        *,
        response_text: str,
        http_status: int,
        trace_id: Any,
    ) -> list[NormalizedVendorSignal]:
        try:
            data = json.loads(response_text)
        except json.JSONDecodeError as e:
            raise VendorUpstreamError(
                vendor_id=self.vendor_id,
                message=f"invalid JSON from vendor: {e}",
                trace_id=trace_id,
                http_status=http_status,
            ) from e
        if not isinstance(data, dict):
            raise VendorUpstreamError(
                vendor_id=self.vendor_id,
                message="vendor JSON root must be an object",
                trace_id=trace_id,
                http_status=http_status,
            )
        if data.get("status") != "success":
            raise VendorUpstreamError(
                vendor_id=self.vendor_id,
                message=f"ip-api status={data.get('status')!r} message={data.get('message')!r}",
                trace_id=trace_id,
                http_status=http_status,
            )

        score = 15.0
        reasons: list[str] = ["vendor:ip_api:success"]
        if data.get("proxy") is True:
            score += 35.0
            reasons.append("vendor:ip_api:proxy")
        if data.get("hosting") is True:
            score += 30.0
            reasons.append("vendor:ip_api:hosting")
        if data.get("mobile") is True:
            score += 10.0
            reasons.append("vendor:ip_api:mobile")

        meta = {
            "country": data.get("country"),
            "countryCode": data.get("countryCode"),
            "region": data.get("region"),
            "city": data.get("city"),
            "isp": data.get("isp"),
            "org": data.get("org"),
            "as": data.get("as"),
            "lat": data.get("lat"),
            "lon": data.get("lon"),
            "query": data.get("query"),
        }
        return [
            NormalizedVendorSignal(
                vendor_id=self.vendor_id,
                score_0_100=score,
                reason_codes=reasons,
                raw_meta=meta,
            )
        ]
