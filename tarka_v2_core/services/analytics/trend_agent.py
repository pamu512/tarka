"""Trend engine execution loop: RAG matrix → Ollama forensic envelope → orchestration writeback.

Pairs with :mod:`macro_synthesizer` for ClickHouse baselines and HIL context. Persists triage
tickets and ``PENDING_VALIDATION`` Wasm draft rules to PostgreSQL; optional ClickHouse HIL
feedback via :meth:`TrendAgent.apply_feedback_override`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Final

import httpx
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from tenacity import retry_if_exception, stop_after_attempt, wait_exponential_jitter
from tenacity.asyncio import AsyncRetrying

from macro_synthesizer import (
    HilOverrideType,
    MacroSynthesizer,
    MacroSynthesizerError,
)

logger = logging.getLogger(__name__)

Z_ESCALATION_THRESHOLD: Final[float] = 4.0
_RESOLVED_SYSTEMIC = "RESOLVED_SYSTEMIC"
_RETRYABLE_HTTP = frozenset({429, 502, 503, 504})
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```\s*$", re.IGNORECASE | re.MULTILINE)

FORENSIC_STATISTICIAN_SYSTEM_PROMPT: Final[str] = """You are an automated forensic statistician for payment-fraud velocity baselines.
You are NOT a conversational assistant. You do NOT speculate beyond the supplied JSON evidence.

INPUT: A single JSON object with keys:
- tactical_snapshots (sub-minute buckets, last 24h)
- cascading_baselines (1d, 3d, 7d, 15d, 30d, 45d, 60d, 90d windows: means/std per metric)
- seasonal_historical_3y (same calendar day-of-year + day-of-week across prior years)
- active_hil_overrides / active_hil_exclusions (analyst-approved scope keys)
- z_score_validations (24h observed vs 90d baseline Z-scores)

MANDATORY DECISION RULES (non-negotiable):
1) If a sharp spike appears in sub-minute (tactical_snapshots), sub-24h (z_score_validations), or 1d
   cascading_baselines versus 90d, BUT the pattern is explained by seasonal_historical_3y (matching slices)
   OR covered by active_hil_exclusions / active_hil_overrides (ALLOW_SEASONAL_SPIKE scope),
   you MUST set resolution_status to "RESOLVED_SYSTEMIC", anomaly_detected=false, flag_for_hil_review=false,
   and forensic_rationale must cite the matching seasonal slice or HIL scope_key. STOP — do not escalate.
2) Only when an anomaly is unmanaged (no seasonal match, no HIL coverage) AND |Z| > 4.0 in z_score_validations,
   set anomaly_detected=true, flag_for_hil_review=true, and provide target_signature + suggested_action.
3) suggested_action MUST be exactly "BLOCK" or "CHALLENGE".
4) target_signature.metric_key MUST be "sub_1min_velocity" or "failed_auth_velocity".
5) target_signature.scope MUST be "entity" or "regional_subnet".
6) Output ONLY one raw JSON object (no markdown fences, no prose) matching this schema:
{
  "resolution_status": "RESOLVED_SYSTEMIC" | "ESCALATED" | "CLEAR",
  "anomaly_detected": boolean,
  "flag_for_hil_review": boolean,
  "suggested_action": "BLOCK" | "CHALLENGE" | null,
  "target_signature": {
    "metric_key": "sub_1min_velocity" | "failed_auth_velocity",
    "threshold_limit": integer,
    "scope": "entity" | "regional_subnet"
  } | null,
  "forensic_rationale": string
}
"""


class TrendAgentError(RuntimeError):
    """Base error for trend agent failures."""


class OllamaTransportError(TrendAgentError):
    """HTTP transport failure talking to Ollama."""


class OllamaEnvelopeError(TrendAgentError):
    """Model output failed JSON/schema validation."""


class TrendPersistenceError(TrendAgentError):
    """PostgreSQL persistence failure."""


class TrendAgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ollama_base_url: str = Field(
        default="http://127.0.0.1:11434",
        validation_alias=AliasChoices("OLLAMA_HOST", "OLLAMA_BASE_URL", "ollama_base_url"),
    )
    ollama_model: str = Field(default="llama3.2", validation_alias="OLLAMA_MODEL")
    ollama_read_timeout_s: float = Field(default=300.0, validation_alias="OLLAMA_READ_TIMEOUT_S")
    ollama_connect_timeout_s: float = Field(default=15.0, validation_alias="OLLAMA_CONNECT_TIMEOUT_S")
    ollama_max_retries: int = Field(default=5, validation_alias="OLLAMA_MAX_RETRIES")
    trend_database_url: str = Field(
        default="",
        validation_alias="TREND_AGENT_DATABASE_URL",
    )
    orchestrator_rules_notify_url: str = Field(
        default="",
        validation_alias="TREND_AGENT_ORCHESTRATOR_NOTIFY_URL",
    )
    z_escalation_threshold: float = Field(default=Z_ESCALATION_THRESHOLD)


class ResolutionStatus(str, Enum):
    RESOLVED_SYSTEMIC = "RESOLVED_SYSTEMIC"
    ESCALATED = "ESCALATED"
    CLEAR = "CLEAR"


class SuggestedAction(str, Enum):
    BLOCK = "BLOCK"
    CHALLENGE = "CHALLENGE"


class MetricKey(str, Enum):
    SUB_1MIN_VELOCITY = "sub_1min_velocity"
    FAILED_AUTH_VELOCITY = "failed_auth_velocity"


class TargetScope(str, Enum):
    ENTITY = "entity"
    REGIONAL_SUBNET = "regional_subnet"


class TargetSignature(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    metric_key: MetricKey
    threshold_limit: int = Field(ge=0)
    scope: TargetScope


class TrendDecisionEnvelope(BaseModel):
    """LLM decision envelope (strict subset enforced before persistence)."""

    model_config = ConfigDict(strict=True, extra="forbid")

    resolution_status: ResolutionStatus
    anomaly_detected: bool
    flag_for_hil_review: bool
    suggested_action: SuggestedAction | None = None
    target_signature: TargetSignature | None = None
    forensic_rationale: str = Field(min_length=1)

    @field_validator("suggested_action", mode="before")
    @classmethod
    def _empty_action_to_none(cls, value: object) -> object:
        if value is None or value == "":
            return None
        return value

    @field_validator("target_signature", mode="before")
    @classmethod
    def _empty_signature_to_none(cls, value: object) -> object:
        if value is None or value == {}:
            return None
        return value


class TrendEvaluationResult(BaseModel):
    model_config = ConfigDict(strict=True)

    tenant_id: str
    entity_id: str
    rag_matrix: dict[str, Any]
    envelope: TrendDecisionEnvelope
    terminated_early: bool
    triage_ticket_id: str | None = None
    draft_rule_id: str | None = None


class _TrendBase(DeclarativeBase):
    pass


class TrendTriageTicketORM(_TrendBase):
    __tablename__ = "trend_triage_tickets"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="OPEN")
    max_z_score: Mapped[float | None] = mapped_column(nullable=True)
    envelope_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    rag_matrix_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class TrendDraftRuleORM(_TrendBase):
    __tablename__ = "trend_draft_rules"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="PENDING_VALIDATION")
    rule_package_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    envelope_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


def _strip_json_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = _JSON_FENCE_RE.sub("", text).strip()
    return text


def _max_abs_z_score(rag_matrix: Mapping[str, Any]) -> float:
    validations = rag_matrix.get("z_score_validations") or []
    scores: list[float] = []
    for item in validations:
        if isinstance(item, Mapping):
            try:
                scores.append(abs(float(item.get("z_score", 0.0))))
            except (TypeError, ValueError):
                continue
    return max(scores) if scores else 0.0


def _seasonal_explains_spike(rag_matrix: Mapping[str, Any]) -> bool:
    seasonal = rag_matrix.get("seasonal_historical_3y")
    if not isinstance(seasonal, Mapping):
        return False
    slices = seasonal.get("slices") or []
    if not slices:
        return False
    baselines = rag_matrix.get("cascading_baselines") or {}
    one_day = baselines.get("1d") if isinstance(baselines, Mapping) else None
    ninety_day = baselines.get("90d") if isinstance(baselines, Mapping) else None
    if not isinstance(one_day, Mapping) or not isinstance(ninety_day, Mapping):
        return bool(slices)
    try:
        one_mean = float(one_day.get("tx_volume_mean", 0.0))
        ninety_mean = float(ninety_day.get("tx_volume_mean", 0.0))
    except (TypeError, ValueError):
        return bool(slices)
    if ninety_mean <= 0.0:
        return bool(slices)
    if one_mean <= ninety_mean * 1.25:
        return False
    for sl in slices:
        if not isinstance(sl, Mapping):
            continue
        try:
            hist_mean = float(sl.get("tx_volume_mean", 0.0))
        except (TypeError, ValueError):
            continue
        if hist_mean <= 0.0:
            continue
        if one_mean <= hist_mean * 1.5 and one_mean >= hist_mean * 0.5:
            return True
    return False


def _hil_covers_spike(rag_matrix: Mapping[str, Any]) -> bool:
    """True when analyst HIL rows document verified seasonal / baseline coverage."""
    if rag_matrix.get("active_hil_exclusions"):
        return True
    for row in rag_matrix.get("active_hil_overrides") or []:
        if not isinstance(row, Mapping):
            continue
        otype = str(row.get("override_type", ""))
        if otype == HilOverrideType.ALLOW_SEASONAL_SPIKE.value or otype.endswith(
            "ALLOW_SEASONAL_SPIKE"
        ):
            return True
    return False


def envelope_action_payload(envelope: TrendDecisionEnvelope) -> dict[str, Any]:
    """Public orchestration JSON (rule promotion / triage UI)."""
    payload: dict[str, Any] = {
        "anomaly_detected": envelope.anomaly_detected,
        "flag_for_hil_review": envelope.flag_for_hil_review,
        "suggested_action": (
            envelope.suggested_action.value if envelope.suggested_action is not None else None
        ),
        "target_signature": (
            envelope.target_signature.model_dump(mode="json")
            if envelope.target_signature is not None
            else None
        ),
        "forensic_rationale": envelope.forensic_rationale,
    }
    return payload


def _tactical_spike_detected(rag_matrix: Mapping[str, Any]) -> bool:
    tactical = rag_matrix.get("tactical_snapshots") or []
    if not tactical:
        return False
    baselines = rag_matrix.get("cascading_baselines") or {}
    ninety = baselines.get("90d") if isinstance(baselines, Mapping) else None
    if not isinstance(ninety, Mapping):
        return len(tactical) > 0
    try:
        mu = float(ninety.get("tx_volume_mean", 0.0))
        sigma = float(ninety.get("tx_volume_std", 0.0))
    except (TypeError, ValueError):
        return len(tactical) > 0
    sigma_use = sigma if sigma > 1e-6 else 1.0
    recent_sum = 0.0
    for row in tactical[-5:]:
        if isinstance(row, Mapping):
            try:
                recent_sum += float(row.get("tx_volume_usd", 0.0))
            except (TypeError, ValueError):
                continue
    if recent_sum <= 0.0:
        return False
    z = (recent_sum - mu) / sigma_use
    return z > 2.0


def try_resolve_systemic(rag_matrix: Mapping[str, Any]) -> TrendDecisionEnvelope | None:
    """Deterministic pre-LLM gate for analyst/HIL/seasonal resolution."""
    spike = _tactical_spike_detected(rag_matrix) or _short_window_spike(rag_matrix)
    if not spike:
        return None
    if not (_seasonal_explains_spike(rag_matrix) or _hil_covers_spike(rag_matrix)):
        return None
    rationale_parts: list[str] = []
    if _seasonal_explains_spike(rag_matrix):
        rationale_parts.append(
            "Velocity spike aligns with seasonal_historical_3y calendar slice; treated as systemic."
        )
    if _hil_covers_spike(rag_matrix):
        rationale_parts.append(
            "active_hil_exclusions document analyst-verified ALLOW_SEASONAL_SPIKE coverage."
        )
    return TrendDecisionEnvelope(
        resolution_status=ResolutionStatus.RESOLVED_SYSTEMIC,
        anomaly_detected=False,
        flag_for_hil_review=False,
        suggested_action=None,
        target_signature=None,
        forensic_rationale=" ".join(rationale_parts) or "Systemic resolution per HIL/seasonal matrix.",
    )


def _short_window_spike(rag_matrix: Mapping[str, Any]) -> bool:
    baselines = rag_matrix.get("cascading_baselines") or {}
    if not isinstance(baselines, Mapping):
        return False
    one_day = baselines.get("1d")
    ninety_day = baselines.get("90d")
    if not isinstance(one_day, Mapping) or not isinstance(ninety_day, Mapping):
        return False
    try:
        one_mean = float(one_day.get("tx_volume_mean", 0.0))
        ninety_mean = float(ninety_day.get("tx_volume_mean", 0.0))
        ninety_std = float(ninety_day.get("tx_volume_std", 0.0))
    except (TypeError, ValueError):
        return False
    sigma = ninety_std if ninety_std > 1e-6 else 1.0
    return one_mean > ninety_mean + 2.0 * sigma


def build_draft_rule_package(
    envelope: TrendDecisionEnvelope,
    *,
    tenant_id: str,
    entity_id: str,
) -> dict[str, Any]:
    """Wasm-oriented draft rule package for dashboard promotion."""
    sig = envelope.target_signature
    metric = sig.metric_key.value if sig is not None else MetricKey.SUB_1MIN_VELOCITY.value
    scope = sig.scope.value if sig is not None else TargetScope.ENTITY.value
    threshold = sig.threshold_limit if sig is not None else 0
    action = (
        envelope.suggested_action.value
        if envelope.suggested_action is not None
        else SuggestedAction.CHALLENGE.value
    )
    return {
        "schema_version": "trend_draft_v1",
        "status": "PENDING_VALIDATION",
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "wasm_ready": True,
        "rule": {
            "id": f"trend-draft-{uuid.uuid4()}",
            "name": f"Trend anomaly gate ({metric})",
            "enabled": False,
            "action": action,
            "predicate": {
                "metric_key": metric,
                "op": "gte",
                "threshold": threshold,
                "scope": scope,
            },
        },
        "forensic_rationale": envelope.forensic_rationale,
        "source": "trend_agent",
    }


class OllamaAsyncClient:
    """Async httpx client for Ollama ``/api/chat`` with retries."""

    def __init__(self, settings: TrendAgentSettings, *, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._base_url = (settings.ollama_base_url or "http://127.0.0.1:11434").rstrip("/")
        self._own_client = client is None
        timeout = httpx.Timeout(
            connect=settings.ollama_connect_timeout_s,
            read=settings.ollama_read_timeout_s,
            write=60.0,
            pool=10.0,
        )
        self._client = client or httpx.AsyncClient(base_url=self._base_url, timeout=timeout)

    async def aclose(self) -> None:
        if self._own_client:
            await self._client.aclose()

    @staticmethod
    def _is_retryable(exc: BaseException) -> bool:
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in _RETRYABLE_HTTP
        return isinstance(
            exc,
            (
                httpx.ConnectError,
                httpx.ConnectTimeout,
                httpx.ReadTimeout,
                httpx.WriteTimeout,
                httpx.PoolTimeout,
                httpx.RemoteProtocolError,
            ),
        )

    async def chat_json(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        model: str | None = None,
    ) -> dict[str, Any]:
        body = {
            "model": (model or self._settings.ollama_model).strip(),
            "messages": [dict(m) for m in messages],
            "stream": False,
            "format": "json",
        }

        async def _post() -> dict[str, Any]:
            response = await self._client.post("/api/chat", json=body)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise OllamaTransportError("Ollama /api/chat returned non-object JSON")
            return payload

        retrying = AsyncRetrying(
            stop=stop_after_attempt(max(int(self._settings.ollama_max_retries), 1)),
            wait=wait_exponential_jitter(initial=0.5, max=30.0),
            retry=retry_if_exception(self._is_retryable),
            reraise=True,
        )
        try:
            async for attempt in retrying:
                with attempt:
                    return await _post()
        except httpx.PoolTimeout as exc:
            raise OllamaTransportError("Ollama connection pool exhausted") from exc
        except httpx.HTTPError as exc:
            raise OllamaTransportError(f"Ollama chat failed: {exc}") from exc

    async def parse_envelope(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        json_retries: int = 2,
    ) -> TrendDecisionEnvelope:
        thread = [dict(m) for m in messages]
        last_raw: str | None = None
        for attempt in range(json_retries + 1):
            payload = await self.chat_json(thread)
            msg = payload.get("message")
            if not isinstance(msg, dict):
                raise OllamaEnvelopeError("Ollama response missing message object")
            content = msg.get("content")
            if not isinstance(content, str):
                raise OllamaEnvelopeError("Ollama message.content is not a string")
            last_raw = content
            try:
                parsed = json.loads(_strip_json_fences(content))
            except json.JSONDecodeError as exc:
                if attempt >= json_retries:
                    raise OllamaEnvelopeError(
                        f"Model output is not valid JSON after {json_retries} retries"
                    ) from exc
                thread.append({"role": "assistant", "content": content})
                thread.append(
                    {
                        "role": "user",
                        "content": "Invalid JSON. Return ONLY the schema object, no fences.",
                    }
                )
                continue
            try:
                return TrendDecisionEnvelope.model_validate(parsed)
            except ValidationError as exc:
                if attempt >= json_retries:
                    raise OllamaEnvelopeError(f"Envelope schema validation failed: {exc}") from exc
                thread.append({"role": "assistant", "content": content})
                thread.append(
                    {
                        "role": "user",
                        "content": "JSON does not match required schema. Fix all fields and retry.",
                    }
                )
        raise OllamaEnvelopeError(f"Envelope parse exhausted retries; last={last_raw!r}")


class TrendAgent:
    """Closed-loop trend evaluator: synthesize → infer → persist → optional notify."""

    def __init__(
        self,
        *,
        settings: TrendAgentSettings | None = None,
        synthesizer: MacroSynthesizer | None = None,
        ollama: OllamaAsyncClient | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._settings = settings or TrendAgentSettings()
        self._synthesizer = synthesizer or MacroSynthesizer()
        self._ollama = ollama or OllamaAsyncClient(self._settings)
        self._session_factory = session_factory
        self._engine: AsyncEngine | None = None

    async def _ensure_session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is not None:
            return self._session_factory
        url = (self._settings.trend_database_url or "").strip()
        if not url:
            raise TrendPersistenceError(
                "TREND_AGENT_DATABASE_URL is required for triage/draft persistence"
            )
        if self._engine is None:
            self._engine = create_async_engine(url, pool_pre_ping=True)
            self._session_factory = async_sessionmaker(
                self._engine,
                expire_on_commit=False,
                class_=AsyncSession,
            )
        assert self._session_factory is not None
        return self._session_factory

    async def aclose(self) -> None:
        await self._ollama.aclose()
        self._synthesizer.close()
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None

    async def run_evaluation_loop(
        self,
        tenant_id: str,
        entity_id: str,
        *,
        region_code: str = "",
    ) -> TrendEvaluationResult:
        """Full loop: compile RAG → resolve/LLM → persist side effects."""
        tenant = tenant_id.strip()
        entity = entity_id.strip()
        if not tenant or not entity:
            raise ValueError("tenant_id and entity_id are required")

        rag_matrix = await asyncio.to_thread(
            self._synthesizer.compile_rag_matrix,
            tenant,
            entity,
            region_code=region_code,
        )

        systemic = try_resolve_systemic(rag_matrix)
        if systemic is not None:
            logger.info(
                "trend_agent_resolved_systemic tenant=%s entity=%s",
                tenant,
                entity,
            )
            return TrendEvaluationResult(
                tenant_id=tenant,
                entity_id=entity,
                rag_matrix=rag_matrix,
                envelope=systemic,
                terminated_early=True,
            )

        messages = [
            {"role": "system", "content": FORENSIC_STATISTICIAN_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(rag_matrix, separators=(",", ":"), default=str),
            },
        ]
        envelope = await self._ollama.parse_envelope(messages)
        envelope = self._apply_escalation_policy(envelope, rag_matrix)

        triage_id: str | None = None
        draft_id: str | None = None

        if envelope.flag_for_hil_review and envelope.anomaly_detected:
            triage_id = await self._persist_triage_ticket(
                tenant,
                entity,
                rag_matrix=rag_matrix,
                envelope=envelope,
            )
            draft_id = await self._persist_draft_rule(tenant, entity, envelope=envelope)
            await self._notify_orchestrator(tenant, entity, envelope=envelope, draft_rule_id=draft_id)

        return TrendEvaluationResult(
            tenant_id=tenant,
            entity_id=entity,
            rag_matrix=rag_matrix,
            envelope=envelope,
            terminated_early=False,
            triage_ticket_id=triage_id,
            draft_rule_id=draft_id,
        )

    def _apply_escalation_policy(
        self,
        envelope: TrendDecisionEnvelope,
        rag_matrix: Mapping[str, Any],
    ) -> TrendDecisionEnvelope:
        max_z = _max_abs_z_score(rag_matrix)
        threshold = float(self._settings.z_escalation_threshold)
        if envelope.resolution_status == ResolutionStatus.RESOLVED_SYSTEMIC:
            return envelope.model_copy(
                update={
                    "anomaly_detected": False,
                    "flag_for_hil_review": False,
                    "suggested_action": None,
                    "target_signature": None,
                }
            )
        if max_z <= threshold and envelope.resolution_status != ResolutionStatus.ESCALATED:
            return envelope.model_copy(
                update={
                    "resolution_status": ResolutionStatus.CLEAR,
                    "anomaly_detected": False,
                    "flag_for_hil_review": False,
                    "suggested_action": None,
                    "target_signature": None,
                }
            )
        if max_z > threshold and not _seasonal_explains_spike(rag_matrix) and not _hil_covers_spike(
            rag_matrix
        ):
            updates: dict[str, Any] = {
                "resolution_status": ResolutionStatus.ESCALATED,
                "anomaly_detected": True,
                "flag_for_hil_review": True,
            }
            if envelope.suggested_action is None:
                updates["suggested_action"] = SuggestedAction.CHALLENGE
            if envelope.target_signature is None:
                metric = MetricKey.FAILED_AUTH_VELOCITY
                validations = rag_matrix.get("z_score_validations") or []
                for v in validations:
                    if isinstance(v, Mapping) and v.get("metric") == "failed_auth_count":
                        metric = MetricKey.FAILED_AUTH_VELOCITY
                        break
                updates["target_signature"] = TargetSignature(
                    metric_key=metric,
                    threshold_limit=max(1, int(max_z * 10)),
                    scope=TargetScope.ENTITY,
                )
            return envelope.model_copy(update=updates)
        return envelope

    async def _persist_triage_ticket(
        self,
        tenant_id: str,
        entity_id: str,
        *,
        rag_matrix: Mapping[str, Any],
        envelope: TrendDecisionEnvelope,
    ) -> str:
        factory = await self._ensure_session_factory()
        ticket_id = uuid.uuid4()
        max_z = _max_abs_z_score(rag_matrix)
        async with factory() as session:
            try:
                session.add(
                    TrendTriageTicketORM(
                        id=ticket_id,
                        tenant_id=tenant_id,
                        entity_id=entity_id,
                        status="OPEN",
                        max_z_score=max_z,
                        envelope_json={
                            **envelope.model_dump(mode="json"),
                            "action_payload": envelope_action_payload(envelope),
                        },
                        rag_matrix_json=dict(rag_matrix),
                    )
                )
                await session.commit()
            except Exception as exc:
                await session.rollback()
                if "too many connections" in str(exc).lower():
                    raise TrendPersistenceError(
                        "PostgreSQL connection pool exhausted during triage insert"
                    ) from exc
                raise TrendPersistenceError(f"triage ticket insert failed: {exc}") from exc
        logger.info(
            "trend_triage_ticket_created id=%s tenant=%s entity=%s max_z=%.3f",
            ticket_id,
            tenant_id,
            entity_id,
            max_z,
        )
        return str(ticket_id)

    async def _persist_draft_rule(
        self,
        tenant_id: str,
        entity_id: str,
        *,
        envelope: TrendDecisionEnvelope,
    ) -> str:
        factory = await self._ensure_session_factory()
        draft_id = uuid.uuid4()
        package = build_draft_rule_package(envelope, tenant_id=tenant_id, entity_id=entity_id)
        async with factory() as session:
            try:
                session.add(
                    TrendDraftRuleORM(
                        id=draft_id,
                        tenant_id=tenant_id,
                        entity_id=entity_id,
                        status="PENDING_VALIDATION",
                        rule_package_json=package,
                        envelope_json={
                            **envelope.model_dump(mode="json"),
                            "action_payload": envelope_action_payload(envelope),
                        },
                    )
                )
                await session.commit()
            except Exception as exc:
                await session.rollback()
                if "too many connections" in str(exc).lower():
                    raise TrendPersistenceError(
                        "PostgreSQL connection pool exhausted during draft rule insert"
                    ) from exc
                raise TrendPersistenceError(f"draft rule insert failed: {exc}") from exc
        logger.info(
            "trend_draft_rule_created id=%s tenant=%s entity=%s",
            draft_id,
            tenant_id,
            entity_id,
        )
        return str(draft_id)

    async def _notify_orchestrator(
        self,
        tenant_id: str,
        entity_id: str,
        *,
        envelope: TrendDecisionEnvelope,
        draft_rule_id: str | None,
    ) -> None:
        url = (self._settings.orchestrator_rules_notify_url or "").strip()
        if not url:
            return
        body = {
            "tenant_id": tenant_id,
            "entity_id": entity_id,
            "draft_rule_id": draft_rule_id,
            "envelope": envelope.model_dump(mode="json"),
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
                response = await client.post(url, json=body)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning(
                "trend_agent_orchestrator_notify_failed url=%s error=%s",
                url,
                exc,
            )

    def apply_feedback_override(
        self,
        tenant_id: str,
        entity_id: str,
        override_type: HilOverrideType | str,
        *,
        scope_key: str,
        expires_at: datetime | None = None,
        analyst_rationale: str = "",
        region_code: str = "",
    ) -> dict[str, Any]:
        """Analyst feedback → ClickHouse ``hil_context_overrides`` (next-iteration calibration).

        This is the production integration point for the dashboard promote/reject flow:
        when an analyst accepts a seasonal explanation, call with
        ``ALLOW_SEASONAL_SPIKE`` and a calendar ``scope_key`` (e.g. ``day_of_year:340``).
        """
        tenant = tenant_id.strip()
        entity = entity_id.strip()
        if not tenant or not entity:
            raise ValueError("tenant_id and entity_id are required")

        if isinstance(override_type, HilOverrideType):
            otype = override_type
        else:
            otype = HilOverrideType(str(override_type).strip())

        expiry = expires_at or (datetime.now(tz=UTC) + timedelta(days=90))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        else:
            expiry = expiry.astimezone(UTC)

        scope = (scope_key or "").strip()
        if not scope:
            anchor = datetime.now(tz=UTC)
            scope = f"day_of_year:{int(anchor.timetuple().tm_yday)}"
            if region_code.strip():
                scope = f"global_region:{region_code.strip()}"

        rationale = (analyst_rationale or "").strip() or (
            f"Analyst feedback via trend_agent ({otype.value})"
        )

        try:
            self._synthesizer.insert_hil_override(
                tenant,
                entity,
                otype,
                scope_key=scope,
                expires_at=expiry,
                analyst_rationale=rationale,
            )
        except (MacroSynthesizerError):
            raise
        except Exception as exc:
            if "too many connections" in str(exc).lower():
                raise MacroSynthesizerError(
                    "ClickHouse connection exhausted during HIL override insert"
                ) from exc
            raise MacroSynthesizerError(f"HIL override insert failed: {exc}") from exc

        record = {
            "tenant_id": tenant,
            "entity_id": entity,
            "override_type": otype.value,
            "scope_key": scope,
            "expires_at": expiry.isoformat(),
            "analyst_rationale": rationale,
        }
        logger.info("trend_agent_hil_override_applied %s", record)
        return record


async def run_trend_evaluation(
    tenant_id: str,
    entity_id: str,
    *,
    region_code: str = "",
    settings: TrendAgentSettings | None = None,
) -> TrendEvaluationResult:
    """Convenience entrypoint: open agent, run loop, always close resources."""
    agent = TrendAgent(settings=settings)
    try:
        return await agent.run_evaluation_loop(tenant_id, entity_id, region_code=region_code)
    finally:
        await agent.aclose()
