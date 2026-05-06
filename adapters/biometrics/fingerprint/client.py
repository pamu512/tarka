"""Async Fingerprint Server API v3 client (``GET /events/{request_id}``).

Authentication per published OpenAPI: header ``Auth-API-Key: <secret>``.

Environment variables (optional defaults in :class:`FingerprintClientSettings`):

- ``FINGERPRINT_SECRET_API_KEY`` — required for outbound calls.
- ``FINGERPRINT_API_BASE_URL`` — override full origin (e.g. ``https://eu.api.fpjs.io``).
- ``FINGERPRINT_REGION`` — ``global`` (default), ``eu``, or ``ap`` when base URL is not overridden.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .exceptions import (
    FingerprintAuthenticationError,
    FingerprintCircuitOpenError,
    FingerprintMalformedPayloadError,
    FingerprintRateLimitError,
    FingerprintRequestNotFoundError,
    FingerprintUpstreamError,
)
from .schemas import EventsGetResponse, TarkaRiskSignal, fingerprint_events_response_to_tarka

RegionName = Literal["global", "eu", "ap"]

_DEFAULT_BASE: dict[RegionName, str] = {
    "global": "https://api.fpjs.io",
    "eu": "https://eu.api.fpjs.io",
    "ap": "https://ap.api.fpjs.io",
}


class FingerprintClientSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    secret_api_key: str = Field(default="", min_length=1, description="Fingerprint secret API key")
    api_base_url: str | None = Field(default=None, max_length=512)
    region: RegionName = "global"
    connect_timeout_s: float = Field(default=3.0, ge=0.5, le=30.0)
    read_timeout_s: float = Field(default=15.0, ge=1.0, le=120.0)
    write_timeout_s: float = Field(default=10.0, ge=1.0, le=120.0)
    pool_timeout_s: float = Field(default=5.0, ge=0.5, le=60.0)
    max_retries: int = Field(default=5, ge=1, le=12)
    backoff_base_s: float = Field(default=0.35, ge=0.05, le=10.0)
    backoff_max_s: float = Field(default=30.0, ge=1.0, le=300.0)
    jitter_ratio: float = Field(default=0.22, ge=0.0, le=0.5)
    circuit_failure_threshold: int = Field(default=5, ge=1, le=50)
    circuit_open_seconds: float = Field(default=45.0, ge=5.0, le=600.0)

    @field_validator("secret_api_key")
    @classmethod
    def strip_secret(cls, v: str) -> str:
        s = (v or "").strip()
        return s

    def resolved_base_url(self) -> str:
        if self.api_base_url:
            return str(self.api_base_url).strip().rstrip("/")
        return _DEFAULT_BASE[self.region]


class _CircuitBreaker:
    def __init__(self, *, failure_threshold: int, open_seconds: float) -> None:
        self._failure_threshold = failure_threshold
        self._open_seconds = open_seconds
        self._failures = 0
        self._open_until = 0.0

    def _now(self) -> float:
        return time.monotonic()

    def before_call(self) -> None:
        if self._now() < self._open_until:
            raise FingerprintCircuitOpenError(
                "Fingerprint client circuit is open due to repeated upstream failures."
            )

    def record_success(self) -> None:
        self._failures = 0
        self._open_until = 0.0

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._failure_threshold:
            self._open_until = self._now() + self._open_seconds
            self._failures = 0


def _parse_retry_after(headers: httpx.Headers) -> float | None:
    raw = headers.get("retry-after") or headers.get("Retry-After")
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _jitter_delay(base: float, *, jitter_ratio: float) -> float:
    if jitter_ratio <= 0:
        return base
    lo = base * (1.0 - jitter_ratio)
    hi = base * (1.0 + jitter_ratio)
    return max(0.0, random.uniform(lo, hi))


class FingerprintClient:
    """Production-oriented async client with retries, ``Retry-After`` support, and circuit breaking."""

    def __init__(
        self,
        settings: FingerprintClientSettings,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._owns_client = http_client is None
        timeout = httpx.Timeout(
            connect=settings.connect_timeout_s,
            read=settings.read_timeout_s,
            write=settings.write_timeout_s,
            pool=settings.pool_timeout_s,
        )
        limits = httpx.Limits(max_keepalive_connections=20, max_connections=100)
        self._http = http_client or httpx.AsyncClient(
            timeout=timeout,
            limits=limits,
            headers={
                "User-Agent": "tarka-fingerprint-adapter/1.0",
                "Accept": "application/json",
            },
        )
        self._circuit = _CircuitBreaker(
            failure_threshold=settings.circuit_failure_threshold,
            open_seconds=settings.circuit_open_seconds,
        )

    @property
    def region_base_url(self) -> str:
        return self._settings.resolved_base_url()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def __aenter__(self) -> FingerprintClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()

    def _require_key(self) -> str:
        if not self._settings.secret_api_key:
            raise FingerprintAuthenticationError(
                "FINGERPRINT_SECRET_API_KEY is not set or empty.",
                fp_error_code="TokenRequired",
                http_status=403,
            )
        return self._settings.secret_api_key

    def _map_error_response(
        self,
        status_code: int,
        text: str,
        *,
        request_id: str = "",
        response_headers: httpx.Headers | None = None,
    ) -> None:
        try:
            body = json.loads(text)
        except json.JSONDecodeError as e:
            raise FingerprintMalformedPayloadError(
                f"Fingerprint error response is not JSON (status={status_code}): {e}"
            ) from e
        err = body.get("error") if isinstance(body, dict) else None
        code = err.get("code") if isinstance(err, dict) else None
        message = err.get("message") if isinstance(err, dict) else None
        if status_code == 404:
            raise FingerprintRequestNotFoundError(
                message or "request id is not found",
                request_id=request_id,
            )
        if status_code == 403 and isinstance(code, str):
            raise FingerprintAuthenticationError(
                message or "forbidden",
                fp_error_code=code,
                http_status=403,
            )
        if status_code == 429:
            ra = _parse_retry_after(response_headers) if response_headers else None
            raise FingerprintRateLimitError(message or "rate limited", retry_after_seconds=ra)
        if 500 <= status_code < 600:
            raise FingerprintUpstreamError(
                message or f"upstream status {status_code}",
                http_status=status_code,
            )
        raise FingerprintUpstreamError(
            message or f"unexpected fingerprint status {status_code}",
            http_status=status_code,
        )

    async def get_event_raw(self, request_id: str) -> tuple[int, str, httpx.Headers]:
        """Return status, text, headers after retries (caller parses JSON)."""

        rid = (request_id or "").strip()
        if not rid:
            raise FingerprintMalformedPayloadError("request_id must be a non-empty string")

        key = self._require_key()
        from urllib.parse import quote

        safe_rid = quote(rid, safe="")
        url = f"{self.region_base_url}/events/{safe_rid}"

        headers = {"Auth-API-Key": key}
        self._circuit.before_call()

        last_exc: Exception | None = None
        last_status: int | None = None
        last_text: str = ""
        last_hdrs: httpx.Headers = httpx.Headers()
        for attempt in range(self._settings.max_retries):
            try:
                resp = await self._http.get(url, headers=headers)
                text = resp.text
                last_status, last_text, last_hdrs = resp.status_code, text, resp.headers
                if resp.status_code == 200:
                    self._circuit.record_success()
                    return resp.status_code, text, resp.headers

                if resp.status_code in (429, 500, 502, 503, 504):
                    self._circuit.record_failure()
                    ra = _parse_retry_after(resp.headers)
                    exp = min(
                        self._settings.backoff_max_s,
                        self._settings.backoff_base_s * (2**attempt),
                    )
                    delay = ra if ra is not None else exp
                    delay = _jitter_delay(delay, jitter_ratio=self._settings.jitter_ratio)
                    await asyncio.sleep(delay)
                    continue

                # Client errors (auth, validation, missing id) should not advance the breaker.
                self._circuit.record_success()
                self._map_error_response(
                    resp.status_code, text, request_id=rid, response_headers=resp.headers
                )
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_exc = e
                self._circuit.record_failure()
                delay = min(
                    self._settings.backoff_max_s,
                    self._settings.backoff_base_s * (2**attempt),
                )
                delay = _jitter_delay(delay, jitter_ratio=self._settings.jitter_ratio)
                await asyncio.sleep(delay)
                continue

        self._circuit.record_failure()
        if last_status == 429:
            ra = _parse_retry_after(last_hdrs)
            raise FingerprintRateLimitError(
                last_text[:2048]
                if last_text
                else "Fingerprint rate limit persisted after retries.",
                retry_after_seconds=ra,
            )
        if last_exc:
            raise FingerprintUpstreamError(
                f"Fingerprint request failed after retries: {last_exc}",
                http_status=503,
            ) from last_exc
        if last_status is not None:
            self._map_error_response(
                last_status, last_text, request_id=rid, response_headers=last_hdrs
            )
        raise FingerprintUpstreamError("Fingerprint request failed after retries.", http_status=503)

    async def get_event(self, request_id: str) -> EventsGetResponse:
        rid = (request_id or "").strip()
        _status, text, _ = await self.get_event_raw(rid)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise FingerprintMalformedPayloadError(f"invalid JSON from Fingerprint: {e}") from e
        if not isinstance(data, dict):
            raise FingerprintMalformedPayloadError("Fingerprint JSON root must be an object")
        try:
            return EventsGetResponse.model_validate(data)
        except Exception as e:
            raise FingerprintMalformedPayloadError(
                f"Fingerprint response failed validation: {e}"
            ) from e

    async def get_event_as_tarka_signal(self, request_id: str) -> TarkaRiskSignal:
        envelope = await self.get_event(request_id)
        return fingerprint_events_response_to_tarka(envelope, region_base_url=self.region_base_url)


@asynccontextmanager
async def fingerprint_client_from_env(
    **settings_overrides: Any,
) -> AsyncIterator[FingerprintClient]:
    """Build client from environment (``FINGERPRINT_*``) and ensure closure."""

    import os

    key = os.environ.get("FINGERPRINT_SECRET_API_KEY", "").strip()
    base = os.environ.get("FINGERPRINT_API_BASE_URL", "").strip() or None
    region_raw = os.environ.get("FINGERPRINT_REGION", "global").strip().lower()
    region: RegionName = "global"
    if region_raw in ("eu", "europe"):
        region = "eu"
    elif region_raw in ("ap", "asia", "mumbai"):
        region = "ap"

    cfg = FingerprintClientSettings(
        secret_api_key=key,
        api_base_url=base,
        region=region,
        **settings_overrides,
    )
    client = FingerprintClient(cfg)
    try:
        yield client
    finally:
        await client.aclose()
