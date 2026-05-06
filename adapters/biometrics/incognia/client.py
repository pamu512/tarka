"""Async Incognia API client aligned with ``incognia-api-java`` networking behavior.

- ``POST api/v2/token`` — ``application/x-www-form-urlencoded``,
  ``Authorization: Basic`` (Base64 of ``clientId:clientSecret``).
- Business calls — ``application/json``, ``Authorization: {tokenType} {accessToken}``.
- Optional ``X-Incognia-Latency`` header echoing the previous request duration (ms), matching
  ``TokenAwareNetworkingClient`` semantics.

Environment variables (optional defaults in :class:`IncogniaClientSettings`):

- ``INCOGNIA_CLIENT_ID`` — required for outbound calls.
- ``INCOGNIA_CLIENT_SECRET`` — required for outbound calls.
- ``INCOGNIA_API_BASE_URL`` — override API origin (default ``https://api.incognia.com``).
"""

from __future__ import annotations

import asyncio
import base64
import json
import random
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .exceptions import (
    IncogniaAuthenticationError,
    IncogniaCircuitOpenError,
    IncogniaClientError,
    IncogniaMalformedPayloadError,
    IncogniaRateLimitError,
    IncogniaUpstreamError,
)
from .schemas import (
    PostFeedbackRequestBody,
    PostSignupRequestBody,
    PostTransactionRequestBody,
    SignupAssessment,
    TokenResponse,
    TransactionAssessment,
)

_DEFAULT_API_BASE = "https://api.incognia.com"
_TOKEN_PATH = "api/v2/token"
_TOKEN_FORM_BODY = "grant_type=client_credentials"
_TOKEN_REFRESH_BEFORE_S = 10.0
_EVAL_QUERY_KEY = "eval"
_DRY_RUN_QUERY_KEY = "dry_run"


class IncogniaClientSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    client_id: str = Field(default="", min_length=1)
    client_secret: str = Field(default="", min_length=1)
    api_base_url: str = Field(default=_DEFAULT_API_BASE, max_length=512)
    connect_timeout_s: float = Field(default=3.0, ge=0.5, le=30.0)
    read_timeout_s: float = Field(default=20.0, ge=1.0, le=120.0)
    write_timeout_s: float = Field(default=10.0, ge=1.0, le=120.0)
    pool_timeout_s: float = Field(default=5.0, ge=0.5, le=60.0)
    max_retries: int = Field(default=5, ge=1, le=12)
    backoff_base_s: float = Field(default=0.35, ge=0.05, le=10.0)
    backoff_max_s: float = Field(default=30.0, ge=1.0, le=300.0)
    jitter_ratio: float = Field(default=0.22, ge=0.0, le=0.5)
    circuit_failure_threshold: int = Field(default=5, ge=1, le=50)
    circuit_open_seconds: float = Field(default=45.0, ge=5.0, le=600.0)

    @field_validator("client_id", "client_secret")
    @classmethod
    def strip_secrets(cls, v: str) -> str:
        return (v or "").strip()

    @field_validator("api_base_url")
    @classmethod
    def strip_base(cls, v: str) -> str:
        s = (v or "").strip().rstrip("/")
        return s or _DEFAULT_API_BASE


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
            raise IncogniaCircuitOpenError(
                "Incognia client circuit is open due to repeated upstream failures."
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


def _compact_json_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Drop nulls (already excluded) and empty collections like Jackson ``NON_EMPTY``."""

    out: dict[str, Any] = {}
    for key, val in data.items():
        if val == [] or val == {}:
            continue
        out[key] = val
    return out


def _dump_model(body: BaseModel) -> dict[str, Any]:
    return _compact_json_dict(body.model_dump(mode="json", exclude_none=True))


class IncogniaClient:
    """Production-oriented async client with token lifecycle, retries, and circuit breaking."""

    def __init__(
        self,
        settings: IncogniaClientSettings,
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
                "User-Agent": "tarka-incognia-adapter/1.0",
                "Accept": "application/json",
            },
        )
        self._circuit = _CircuitBreaker(
            failure_threshold=settings.circuit_failure_threshold,
            open_seconds=settings.circuit_open_seconds,
        )
        self._token_lock = asyncio.Lock()
        self._access_token: str | None = None
        self._token_type: str = "Bearer"
        self._token_expires_wall: float = 0.0
        self._last_latency_ms: int | None = None

    @property
    def api_base_url(self) -> str:
        return self._settings.api_base_url

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def __aenter__(self) -> IncogniaClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()

    def _require_credentials(self) -> tuple[str, str]:
        cid = self._settings.client_id
        sec = self._settings.client_secret
        if not cid or not sec:
            raise IncogniaAuthenticationError(
                "INCOGNIA_CLIENT_ID / INCOGNIA_CLIENT_SECRET are not set or empty.",
                http_status=401,
            )
        return cid, sec

    def _token_valid(self) -> bool:
        if not self._access_token:
            return False
        return time.time() < self._token_expires_wall - TOKEN_REFRESH_BEFORE_S

    async def _fetch_token(self) -> None:
        client_id, client_secret = self._require_credentials()
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
        url = f"{self.api_base_url}/{_TOKEN_PATH}"
        self._circuit.before_call()
        t0 = time.perf_counter()
        try:
            resp = await self._http.post(
                url,
                content=_TOKEN_FORM_BODY.encode("utf-8"),
                headers={
                    "Authorization": f"Basic {basic}",
                    "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                },
            )
        except (httpx.TimeoutException, httpx.TransportError) as e:
            self._circuit.record_failure()
            raise IncogniaUpstreamError(f"token request transport failed: {e}", http_status=503) from e

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        self._last_latency_ms = elapsed_ms

        text = resp.text
        if resp.status_code == 200:
            self._circuit.record_success()
            try:
                data = json.loads(text)
            except json.JSONDecodeError as e:
                raise IncogniaMalformedPayloadError(f"token response is not JSON: {e}") from e
            if not isinstance(data, dict):
                raise IncogniaMalformedPayloadError("token response root must be an object")
            try:
                tr = TokenResponse.model_validate(data)
            except Exception as e:
                raise IncogniaMalformedPayloadError(f"token response failed validation: {e}") from e
            self._access_token = tr.access_token
            self._token_type = (tr.token_type or "Bearer").strip()
            self._token_expires_wall = time.time() + float(tr.expires_in)
            return

        if resp.status_code in (401, 403):
            self._circuit.record_success()
            raise IncogniaAuthenticationError(
                f"Incognia token endpoint returned {resp.status_code}: {text[:2048]}",
                http_status=resp.status_code,
            )
        if resp.status_code == 429:
            self._circuit.record_success()
            ra = _parse_retry_after(resp.headers)
            raise IncogniaRateLimitError(
                text[:2048] if text else "rate limited on token endpoint",
                retry_after_seconds=ra,
            )
        if 500 <= resp.status_code < 600:
            self._circuit.record_failure()
            raise IncogniaUpstreamError(
                text[:2048] if text else f"token upstream {resp.status_code}",
                http_status=resp.status_code,
            )
        self._circuit.record_success()
        payload: dict[str, Any] | None
        try:
            payload = json.loads(text) if text else None
        except json.JSONDecodeError:
            payload = None
        raise IncogniaClientError(
            f"Incognia token endpoint returned {resp.status_code}",
            http_status=resp.status_code,
            payload=payload if isinstance(payload, dict) else None,
        )

    async def _ensure_token(self, *, force: bool = False) -> None:
        async with self._token_lock:
            if not force and self._token_valid():
                return
            await self._fetch_token()

    def _auth_headers(self) -> dict[str, str]:
        if not self._access_token:
            raise IncogniaAuthenticationError("internal error: missing access token", http_status=401)
        headers: dict[str, str] = {
            "Authorization": f"{self._token_type} {self._access_token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        if self._last_latency_ms is not None:
            headers["X-Incognia-Latency"] = str(self._last_latency_ms)
        return headers

    def _map_error(
        self,
        status_code: int,
        text: str,
        *,
        response_headers: httpx.Headers | None = None,
    ) -> None:
        payload: dict[str, Any] | None = None
        if text:
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    payload = parsed
            except json.JSONDecodeError:
                payload = None
        if status_code in (401, 403):
            raise IncogniaAuthenticationError(
                text[:2048] if text else f"HTTP {status_code}",
                http_status=status_code,
            )
        if status_code == 429:
            ra = _parse_retry_after(response_headers) if response_headers else None
            raise IncogniaRateLimitError(
                text[:2048] if text else "rate limited",
                retry_after_seconds=ra,
            )
        if 500 <= status_code < 600:
            raise IncogniaUpstreamError(
                text[:2048] if text else f"upstream {status_code}",
                http_status=status_code,
            )
        if 400 <= status_code < 500:
            raise IncogniaClientError(
                text[:2048] if text else f"client error {status_code}",
                http_status=status_code,
                payload=payload,
            )
        raise IncogniaUpstreamError(
            text[:2048] if text else f"unexpected status {status_code}",
            http_status=status_code,
        )

    async def _request_json(
        self,
        method: Literal["POST"],
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, str, httpx.Headers]:
        """Perform one HTTP call with retries for transient errors (caller supplies path without leading slash)."""

        url = f"{self.api_base_url}/{path.lstrip('/')}"
        self._circuit.before_call()

        last_exc: Exception | None = None
        last_status: int | None = None
        last_text: str = ""
        last_hdrs: httpx.Headers = httpx.Headers()
        auth_refresh_used = False

        for attempt in range(self._settings.max_retries):
            await self._ensure_token(force=False)
            headers = self._auth_headers()
            t0 = time.perf_counter()
            try:
                resp = await self._http.request(method, url, headers=headers, json=json_body)
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

            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            self._last_latency_ms = elapsed_ms
            text = resp.text
            last_status, last_text, last_hdrs = resp.status_code, text, resp.headers

            if resp.status_code == 401 and not auth_refresh_used:
                auth_refresh_used = True
                async with self._token_lock:
                    self._access_token = None
                    self._token_expires_wall = 0.0
                try:
                    await self._ensure_token(force=True)
                except IncogniaAuthenticationError:
                    self._circuit.record_success()
                    self._map_error(resp.status_code, text, response_headers=resp.headers)
                continue

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

            self._circuit.record_success()
            self._map_error(resp.status_code, text, response_headers=resp.headers)

        self._circuit.record_failure()
        if last_status == 429:
            ra = _parse_retry_after(last_hdrs)
            raise IncogniaRateLimitError(
                last_text[:2048] if last_text else "Incognia rate limit persisted after retries.",
                retry_after_seconds=ra,
            )
        if last_exc:
            raise IncogniaUpstreamError(
                f"Incognia request failed after retries: {last_exc}",
                http_status=503,
            ) from last_exc
        if last_status is not None:
            self._map_error(last_status, last_text, response_headers=last_hdrs)
        raise IncogniaUpstreamError("Incognia request failed after retries.", http_status=503)

    async def post_signup(self, body: PostSignupRequestBody) -> SignupAssessment:
        """``POST api/v2/onboarding/signups`` — mobile or web signup body per API reference."""

        payload = _dump_model(body)
        _status, text, _ = await self._request_json("POST", "api/v2/onboarding/signups", json_body=payload)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise IncogniaMalformedPayloadError(f"invalid JSON from Incognia: {e}") from e
        if not isinstance(data, dict):
            raise IncogniaMalformedPayloadError("Incognia JSON root must be an object")
        try:
            return SignupAssessment.model_validate(data)
        except Exception as e:
            raise IncogniaMalformedPayloadError(f"signup assessment validation failed: {e}") from e

    async def post_transaction(
        self,
        body: PostTransactionRequestBody,
        *,
        evaluate_transaction: bool | None = None,
    ) -> TransactionAssessment:
        """``POST api/v2/authentication/transactions`` with optional ``eval`` query flag."""

        payload = _dump_model(body)
        path = "api/v2/authentication/transactions"
        if evaluate_transaction is not None:
            path = f"{path}?{_EVAL_QUERY_KEY}={'true' if evaluate_transaction else 'false'}"
        _status, text, _ = await self._request_json("POST", path, json_body=payload)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise IncogniaMalformedPayloadError(f"invalid JSON from Incognia: {e}") from e
        if not isinstance(data, dict):
            raise IncogniaMalformedPayloadError("Incognia JSON root must be an object")
        try:
            return TransactionAssessment.model_validate(data)
        except Exception as e:
            raise IncogniaMalformedPayloadError(f"transaction assessment validation failed: {e}") from e

    async def post_feedback(self, body: PostFeedbackRequestBody, *, dry_run: bool = False) -> None:
        """``POST api/v2/feedbacks`` with ``dry_run`` query parameter (string ``true``/``false``)."""

        payload = _dump_model(body)
        q = "true" if dry_run else "false"
        path = f"api/v2/feedbacks?{_DRY_RUN_QUERY_KEY}={q}"
        await self._request_json("POST", path, json_body=payload)


@asynccontextmanager
async def incognia_client_from_env(
    **settings_overrides: Any,
) -> AsyncIterator[IncogniaClient]:
    """Build client from environment (``INCOGNIA_*``) and ensure closure."""

    import os

    cid = os.environ.get("INCOGNIA_CLIENT_ID", "").strip()
    sec = os.environ.get("INCOGNIA_CLIENT_SECRET", "").strip()
    base = os.environ.get("INCOGNIA_API_BASE_URL", "").strip() or _DEFAULT_API_BASE

    cfg = IncogniaClientSettings(
        client_id=cid,
        client_secret=sec,
        api_base_url=base,
        **settings_overrides,
    )
    client = IncogniaClient(cfg)
    try:
        yield client
    finally:
        await client.aclose()
