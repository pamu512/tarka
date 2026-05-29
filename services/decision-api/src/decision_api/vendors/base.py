"""Vendor adapters, enterprise plugins, and unified signal ontology (0–100 risk scale)."""

from __future__ import annotations

import asyncio
import time
import uuid
from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING, Any, cast

import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential
from tenacity.asyncio import AsyncRetrying

from decision_api.config import settings
from decision_api.vendors.exceptions import (
    VendorAuditConfigurationError,
    VendorTimeoutError,
    VendorUpstreamError,
)

if TYPE_CHECKING:
    pass


class VendorTier(str, Enum):
    CHEAP = "cheap"
    STANDARD = "standard"
    PREMIUM = "premium"


class NormalizedVendorSignal:
    __slots__ = ("vendor_id", "score_0_100", "reason_codes", "raw_meta")

    def __init__(
        self,
        vendor_id: str,
        score_0_100: float,
        reason_codes: list[str],
        raw_meta: dict[str, Any] | None = None,
    ) -> None:
        self.vendor_id = vendor_id
        self.score_0_100 = max(0.0, min(100.0, float(score_0_100)))
        self.reason_codes = reason_codes
        self.raw_meta = raw_meta or {}


class VendorFetchContext(BaseModel):
    """Validated execution context for :meth:`BaseVendorPlugin.fetch_signals`."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    http: httpx.AsyncClient
    session: Any
    trace_id: uuid.UUID
    tenant_id: str = Field(..., max_length=128)
    entity_id: str = Field(..., max_length=512)
    features: dict[str, Any]
    budget_ms: float = Field(..., ge=50.0, le=30_000.0)


class VendorAdapter(ABC):
    """Legacy adapter surface (single primary signal)."""

    vendor_id: str
    tier: VendorTier = VendorTier.STANDARD

    @abstractmethod
    async def fetch_signal(
        self,
        http: httpx.AsyncClient,
        tenant_id: str,
        entity_id: str,
        features: dict[str, Any],
        *,
        budget_ms: float,
        audit_session: AsyncSession | None = None,
        trace_id: uuid.UUID | None = None,
    ) -> NormalizedVendorSignal:
        """Fetch and normalize; plugins require ``audit_session`` + ``trace_id`` for Postgres audit."""

    def cost_weight(self) -> float:
        return {
            VendorTier.CHEAP: 1.0,
            VendorTier.STANDARD: 2.0,
            VendorTier.PREMIUM: 4.0,
        }[self.tier]


class BaseVendorPlugin(VendorAdapter):
    """Enterprise vendor plugin: strict HTTP resilience, Postgres audit of raw payloads, then parse.

    Subclasses implement :meth:`_build_get_url`, :meth:`_parse_vendor_payload`, and :meth:`health_check`.
    Optional :meth:`_credential_model` / stored credentials are validated via Pydantic at construction time
    when provided by the concrete plugin.
    """

    @abstractmethod
    async def health_check(self, http: httpx.AsyncClient) -> dict[str, Any]:
        """Cheap liveness/readiness probe (must not return synthetic vendor scores)."""

    @abstractmethod
    def _build_get_url(self, features: dict[str, Any]) -> str:
        """Return fully qualified GET URL from validated feature mapping."""

    @abstractmethod
    def _parse_vendor_payload(
        self,
        *,
        response_text: str,
        http_status: int,
        trace_id: uuid.UUID | None,
    ) -> list[NormalizedVendorSignal]:
        """Map exact vendor body to normalized signals (non-empty or raise :class:`VendorUpstreamError`)."""

    def _credential_model(self) -> type[BaseModel] | None:
        """Override when the plugin ships a credentials schema (validated once)."""
        return None

    def _validated_credentials(self) -> BaseModel | None:
        return None

    def _max_http_attempts(self) -> int:
        return max(1, min(8, int(settings.vendor_http_max_attempts)))

    def _retry_wait(self) -> tuple[float, float]:
        return (
            float(settings.vendor_http_retry_min_wait),
            float(settings.vendor_http_retry_max_wait),
        )

    async def fetch_signal(
        self,
        http: httpx.AsyncClient,
        tenant_id: str,
        entity_id: str,
        features: dict[str, Any],
        *,
        budget_ms: float,
        audit_session: AsyncSession | None = None,
        trace_id: uuid.UUID | None = None,
    ) -> NormalizedVendorSignal:
        if audit_session is None or trace_id is None:
            raise VendorAuditConfigurationError(
                "BaseVendorPlugin requires audit_session and trace_id for Postgres audit persistence"
            )
        ctx = VendorFetchContext(
            http=http,
            session=audit_session,
            trace_id=trace_id,
            tenant_id=tenant_id,
            entity_id=entity_id,
            features=features,
            budget_ms=budget_ms,
        )
        signals = await self.fetch_signals(ctx)
        if not signals:
            raise VendorUpstreamError(
                vendor_id=self.vendor_id,
                message="vendor returned zero signals after successful HTTP response",
                trace_id=trace_id,
            )
        return signals[0]

    async def fetch_signals(
        self, ctx: VendorFetchContext
    ) -> list[NormalizedVendorSignal]:
        """HTTP GET with tenacity + overall budget, audit raw body + latency, then parse (no silent empty)."""
        url = self._build_get_url(ctx.features)
        budget_s = ctx.budget_ms / 1000.0
        t0 = time.perf_counter()
        resp: httpx.Response | None = None
        raw_text = ""
        http_status: int | None = None

        try:
            resp = await asyncio.wait_for(
                self._resilient_get(ctx.http, url, ctx.budget_ms), timeout=budget_s
            )
            raw_text = resp.text
            http_status = resp.status_code
        except asyncio.TimeoutError:
            latency_ms = (time.perf_counter() - t0) * 1000
            await self._persist_integration_audit(
                ctx,
                request_url=url,
                http_status=http_status,
                latency_ms=latency_ms,
                raw_response=raw_text,
                outcome="timeout",
                error_detail="asyncio.TimeoutError: exceeded budget after retries",
            )
            raise VendorTimeoutError(
                vendor_id=self.vendor_id,
                budget_ms=ctx.budget_ms,
                trace_id=ctx.trace_id,
            ) from None
        except httpx.TimeoutException as e:
            latency_ms = (time.perf_counter() - t0) * 1000
            await self._persist_integration_audit(
                ctx,
                request_url=url,
                http_status=http_status,
                latency_ms=latency_ms,
                raw_response=raw_text,
                outcome="timeout",
                error_detail=str(e)[:8000],
            )
            raise VendorTimeoutError(
                vendor_id=self.vendor_id,
                budget_ms=ctx.budget_ms,
                trace_id=ctx.trace_id,
                message="vendor HTTP layer timed out",
            ) from e
        except Exception as e:
            latency_ms = (time.perf_counter() - t0) * 1000
            await self._persist_integration_audit(
                ctx,
                request_url=url,
                http_status=http_status,
                latency_ms=latency_ms,
                raw_response=raw_text,
                outcome="error",
                error_detail=f"{type(e).__name__}: {e}"[:8000],
            )
            raise

        latency_ms = (time.perf_counter() - t0) * 1000
        await self._persist_integration_audit(
            ctx,
            request_url=url,
            http_status=http_status or (resp.status_code if resp else None),
            latency_ms=latency_ms,
            raw_response=raw_text,
            outcome="success",
            error_detail=None,
        )

        status_code = resp.status_code if resp is not None else 0
        if status_code >= 400:
            raise VendorUpstreamError(
                vendor_id=self.vendor_id,
                message=f"HTTP {status_code} from vendor",
                trace_id=ctx.trace_id,
                http_status=status_code,
            )

        return self._parse_vendor_payload(
            response_text=raw_text,
            http_status=status_code,
            trace_id=ctx.trace_id,
        )

    async def _resilient_get(
        self, http: httpx.AsyncClient, url: str, budget_ms: float
    ) -> httpx.Response:
        attempts = self._max_http_attempts()
        wmin, wmax = self._retry_wait()
        per_read = max(0.25, min(8.0, (budget_ms / 1000.0) / float(attempts)))
        retrying = AsyncRetrying(
            stop=stop_after_attempt(attempts),
            wait=wait_exponential(multiplier=wmin, min=wmin, max=wmax),
            retry=retry_if_exception_type(
                (
                    httpx.TimeoutException,
                    httpx.ConnectError,
                    httpx.ReadError,
                    httpx.RemoteProtocolError,
                    httpx.WriteError,
                )
            ),
            reraise=True,
            sleep=asyncio.sleep,
        )
        async for attempt in retrying:
            with attempt:
                return await http.get(
                    url,
                    follow_redirects=True,
                    timeout=httpx.Timeout(
                        per_read, connect=min(2.0, per_read), pool=min(2.0, per_read)
                    ),
                )
        raise RuntimeError("unreachable: AsyncRetrying must return or raise")

    async def _persist_integration_audit(
        self,
        ctx: VendorFetchContext,
        *,
        request_url: str,
        http_status: int | None,
        latency_ms: float,
        raw_response: str,
        outcome: str,
        error_detail: str | None,
    ) -> None:
        from decision_api.models import VendorIntegrationAudit

        row = VendorIntegrationAudit(
            trace_id=ctx.trace_id,
            tenant_id=ctx.tenant_id,
            entity_id=ctx.entity_id,
            vendor_id=self.vendor_id,
            request_url=request_url[:4096],
            http_status=http_status,
            latency_ms=latency_ms,
            raw_response=raw_response[:1_000_000],
            outcome=outcome,
            error_detail=(error_detail[:16000] if error_detail else None),
        )
        session = cast(AsyncSession, ctx.session)
        session.add(row)
        await session.flush()
