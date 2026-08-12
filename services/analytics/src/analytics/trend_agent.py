"""Omniscient trend agent — forensic statistician, not an autonomous decider.

Compiles a multi-window RAG matrix, resolves seasonal/HIL systemically without LLM,
optionally asks any OpenAI-compatible chat model for a structured envelope, and
persists triage + PENDING_VALIDATION draft rules only (never live Wasm promotion).

The RAG matrix is the contract; the LLM provider is swappable (OpenAI, Azure, vLLM,
Ollama `/v1`, Groq, etc.).
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx

from analytics import trend_store
from analytics.trend_rag import (
    HilOverride,
    RagMatrix,
    compile_rag_matrix,
    try_resolve_systemic,
)

logger = logging.getLogger(__name__)

SuggestedAction = Literal["BLOCK", "CHALLENGE", "MONITOR"]
Disposition = Literal["RESOLVED_SYSTEMIC", "ESCALATED", "MONITOR", "ERROR"]

FORENSIC_STATISTICIAN_SYSTEM_PROMPT = """You are an automated forensic statistician for payment fraud velocity.
You are NOT an autonomous decision-maker. You never approve live rule promotion.

Analyze cascading baseline deviations across the supplied RAG matrix JSON.
Rules:
1. If a sharp spike in sub_1min or sub_24h matches seasonal_historical_3y or active_hil_overrides,
   respond with disposition RESOLVED_SYSTEMIC and anomaly_detected=false.
2. If |Z| > 4.0 with no seasonal/HIL coverage, set anomaly_detected=true, flag_for_hil_review=true,
   disposition ESCALATED, and propose BLOCK or CHALLENGE with a precise target_signature.
3. Otherwise disposition MONITOR, anomaly_detected=false unless evidence clearly warrants CHALLENGE.
4. Output ONE JSON object only (no markdown) matching TrendDecisionEnvelope fields.
"""


@dataclass
class TrendDecisionEnvelope:
    disposition: Disposition
    anomaly_detected: bool
    flag_for_hil_review: bool
    suggested_action: SuggestedAction
    metric_key: str
    threshold_limit: int
    scope: str
    forensic_rationale: str
    max_z_score: float = 0.0
    source: str = "llm"  # llm | systemic | policy | timeout

    def to_dict(self) -> dict[str, Any]:
        return {
            "disposition": self.disposition,
            "anomaly_detected": self.anomaly_detected,
            "flag_for_hil_review": self.flag_for_hil_review,
            "suggested_action": self.suggested_action,
            "target_signature": {
                "metric_key": self.metric_key,
                "threshold_limit": int(self.threshold_limit),
                "scope": self.scope,
            },
            "forensic_rationale": self.forensic_rationale,
            "max_z_score": self.max_z_score,
            "source": self.source,
        }


def envelope_action_payload(envelope: TrendDecisionEnvelope) -> dict[str, Any]:
    """Public orchestration JSON (rule-draft shape)."""
    d = envelope.to_dict()
    return {
        "anomaly_detected": d["anomaly_detected"],
        "flag_for_hil_review": d["flag_for_hil_review"],
        "suggested_action": d["suggested_action"],
        "target_signature": d["target_signature"],
        "forensic_rationale": d["forensic_rationale"],
        "disposition": d["disposition"],
        "max_z_score": d["max_z_score"],
        "source": d["source"],
    }


def _parse_envelope(raw: dict[str, Any], *, max_z: float, source: str) -> TrendDecisionEnvelope:
    sig = raw.get("target_signature") if isinstance(raw.get("target_signature"), dict) else {}
    action = str(raw.get("suggested_action") or "MONITOR").strip().upper()
    if action not in ("BLOCK", "CHALLENGE", "MONITOR"):
        action = "MONITOR"
    disp = str(raw.get("disposition") or "MONITOR").strip().upper()
    if disp not in ("RESOLVED_SYSTEMIC", "ESCALATED", "MONITOR", "ERROR"):
        disp = "MONITOR"
    try:
        threshold = int(sig.get("threshold_limit") or raw.get("threshold_limit") or 0)
    except (TypeError, ValueError):
        threshold = 0
    return TrendDecisionEnvelope(
        disposition=disp,  # type: ignore[arg-type]
        anomaly_detected=bool(raw.get("anomaly_detected")),
        flag_for_hil_review=bool(raw.get("flag_for_hil_review")),
        suggested_action=action,  # type: ignore[arg-type]
        metric_key=str(sig.get("metric_key") or raw.get("metric_key") or "sub_1min_velocity"),
        threshold_limit=threshold,
        scope=str(sig.get("scope") or raw.get("scope") or "entity"),
        forensic_rationale=str(raw.get("forensic_rationale") or "")[:4000],
        max_z_score=float(max_z),
        source=source,
    )


def _policy_escalate(matrix: RagMatrix, reason: str) -> TrendDecisionEnvelope:
    top = max(matrix.windows, key=lambda w: abs(float(w.z_score or 0.0)), default=None)
    metric = top.metric_key if top else "sub_1min_velocity"
    observed = int(top.observed) if top else 0
    return TrendDecisionEnvelope(
        disposition="ESCALATED",
        anomaly_detected=True,
        flag_for_hil_review=True,
        suggested_action="CHALLENGE",
        metric_key=metric,
        threshold_limit=max(observed, 1),
        scope="entity",
        forensic_rationale=f"Policy escalation: {reason}; max_|Z|={matrix.max_abs_z():.2f}",
        max_z_score=matrix.max_abs_z(),
        source="policy",
    )


def _systemic_envelope(matrix: RagMatrix, reason: str) -> TrendDecisionEnvelope:
    return TrendDecisionEnvelope(
        disposition="RESOLVED_SYSTEMIC",
        anomaly_detected=False,
        flag_for_hil_review=False,
        suggested_action="MONITOR",
        metric_key="sub_1min_velocity",
        threshold_limit=0,
        scope="entity",
        forensic_rationale=f"Resolved systemically: {reason}",
        max_z_score=matrix.max_abs_z(),
        source="systemic",
    )


class LlmClient(Protocol):
    async def complete_json(self, *, system: str, user: str) -> dict[str, Any]: ...


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        raw = (os.environ.get(name) or "").strip()
        if raw:
            return raw
    return default


def resolve_llm_base_url() -> str:
    """OpenAI-compatible base (no trailing slash). Ollama is optional via ``…/v1``."""
    return _env_first(
        "TREND_AGENT_LLM_BASE_URL",
        "OPENAI_BASE_URL",
        # Ollama OpenAI-compatible surface (not /api/chat)
        "OLLAMA_OPENAI_BASE_URL",
        default="https://api.openai.com/v1",
    ).rstrip("/")


def resolve_llm_model() -> str:
    return _env_first(
        "TREND_AGENT_LLM_MODEL",
        "OPENAI_MODEL",
        "OLLAMA_MODEL",
        default="gpt-4o-mini",
    )


def resolve_llm_api_key() -> str:
    return _env_first("TREND_AGENT_LLM_API_KEY", "OPENAI_API_KEY", default="")


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("empty_llm_content")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("llm_json_not_object")
    return parsed


@dataclass
class OpenAICompatibleJsonClient:
    """Any OpenAI-compatible ``POST {base}/chat/completions`` provider."""

    base_url: str = field(default_factory=resolve_llm_base_url)
    model: str = field(default_factory=resolve_llm_model)
    api_key: str = field(default_factory=resolve_llm_api_key)
    timeout_s: float = 30.0
    client: httpx.AsyncClient | None = None

    def chat_completions_url(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    async def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        url = self.chat_completions_url()
        owned = self.client is None
        http = self.client or httpx.AsyncClient(timeout=self.timeout_s)
        try:
            resp = await http.post(url, json=payload, headers=headers)
            # Some local servers reject response_format — retry without it once.
            if resp.status_code in (400, 422) and "response_format" in (resp.text or ""):
                payload.pop("response_format", None)
                resp = await http.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            body = resp.json()
            if not isinstance(body, dict):
                raise ValueError("llm_response_not_object")
            choices = body.get("choices")
            if not isinstance(choices, list) or not choices:
                raise ValueError("llm_missing_choices")
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, str):
                raise ValueError("empty_llm_content")
            return _extract_json_object(content)
        finally:
            if owned:
                await http.aclose()


# Backward-compatible name: Ollama is one optional OpenAI-compatible endpoint, not the contract.
OllamaJsonClient = OpenAICompatibleJsonClient


@dataclass
class TrendAgent:
    llm: LlmClient | None = None
    skip_llm: bool = False

    async def run_evaluation_loop(
        self,
        *,
        tenant_id: str,
        entity_id: str,
        region_code: str = "",
        window_rows: list[dict[str, Any]] | None = None,
        hil_overrides: list[HilOverride] | None = None,
    ) -> dict[str, Any]:
        hil = list(hil_overrides or [])
        if not hil:
            stored = trend_store.list_hil_overrides(tenant_id=tenant_id, entity_id=entity_id)
            hil = [
                HilOverride(
                    tenant_id=tenant_id,
                    entity_id=entity_id,
                    override_type=str(r["override_type"]),
                    scope_key=str(r.get("scope_key") or ""),
                    analyst_rationale=str(r.get("analyst_rationale") or ""),
                )
                for r in stored
            ]

        matrix = compile_rag_matrix(
            tenant_id=tenant_id,
            entity_id=entity_id,
            region_code=region_code,
            window_rows=window_rows,
            hil_overrides=hil,
        )
        disposition, reason = try_resolve_systemic(matrix)

        if disposition == "RESOLVED_SYSTEMIC":
            envelope = _systemic_envelope(matrix, reason)
            return self._finalize(matrix, envelope, triage=False, draft=False)

        if disposition == "ESCALATED":
            envelope = _policy_escalate(matrix, reason)
            return self._finalize(matrix, envelope, triage=True, draft=True)

        # NEEDS_LLM
        if self.skip_llm or self.llm is None:
            # Fail closed: unmanaged path without LLM → escalate for HIL, do not clear.
            envelope = _policy_escalate(matrix, "llm_unavailable_fail_closed")
            return self._finalize(matrix, envelope, triage=True, draft=True)

        try:
            raw = await self.llm.complete_json(
                system=FORENSIC_STATISTICIAN_SYSTEM_PROMPT,
                user=json.dumps(matrix.to_dict(), sort_keys=True, default=str),
            )
            envelope = _parse_envelope(raw, max_z=matrix.max_abs_z(), source="llm")
        except (httpx.TimeoutException, httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("trend_agent_llm_failed entity_id=%s exc=%r", entity_id, exc)
            # Timeout / parse failure: escalate for review, never RESOLVED_SYSTEMIC.
            envelope = _policy_escalate(matrix, f"llm_timeout_or_error:{type(exc).__name__}")
            envelope = TrendDecisionEnvelope(
                disposition=envelope.disposition,
                anomaly_detected=True,
                flag_for_hil_review=True,
                suggested_action=envelope.suggested_action,
                metric_key=envelope.metric_key,
                threshold_limit=envelope.threshold_limit,
                scope=envelope.scope,
                forensic_rationale=envelope.forensic_rationale,
                max_z_score=envelope.max_z_score,
                source="timeout",
            )
            return self._finalize(matrix, envelope, triage=True, draft=True)

        # Hard policy: |Z|>4 without seasonal/HIL always escalates regardless of LLM tone.
        if (
            matrix.max_abs_z() > 4.0
            and not matrix.seasonal_match
            and not matrix.hil_overrides
        ):
            envelope.disposition = "ESCALATED"
            envelope.anomaly_detected = True
            envelope.flag_for_hil_review = True
            if envelope.suggested_action == "MONITOR":
                envelope.suggested_action = "CHALLENGE"
            envelope.source = "policy+llm"

        return self._finalize(
            matrix,
            envelope,
            triage=bool(envelope.flag_for_hil_review or envelope.disposition == "ESCALATED"),
            draft=bool(envelope.flag_for_hil_review),
        )

    def _finalize(
        self,
        matrix: RagMatrix,
        envelope: TrendDecisionEnvelope,
        *,
        triage: bool,
        draft: bool,
    ) -> dict[str, Any]:
        action = envelope_action_payload(envelope)
        triage_id = None
        draft_id = None
        if triage:
            triage_id = trend_store.insert_triage_ticket(
                tenant_id=matrix.tenant_id,
                entity_id=matrix.entity_id,
                max_z_score=matrix.max_abs_z(),
                envelope=action,
                rag_matrix=matrix.to_dict(),
            )
        if draft and envelope.flag_for_hil_review:
            rule_package = {
                "format": "tarka.trend_draft_rule/v1",
                # Draft proposal only — never Wasm-ready / never auto-promoted.
                "wasm_ready": False,
                "promotable": False,
                "status": "PENDING_VALIDATION",
                "action": action["suggested_action"],
                "target_signature": action["target_signature"],
                "forensic_rationale": action["forensic_rationale"],
            }
            draft_id = trend_store.insert_draft_rule(
                tenant_id=matrix.tenant_id,
                entity_id=matrix.entity_id,
                rule_package=rule_package,
                envelope=action,
                status="PENDING_VALIDATION",
            )
        return {
            "tenant_id": matrix.tenant_id,
            "entity_id": matrix.entity_id,
            "disposition": envelope.disposition,
            "envelope": action,
            "rag_matrix": matrix.to_dict(),
            "triage_ticket_id": triage_id,
            "draft_rule_id": draft_id,
        }

    def apply_feedback_override(
        self,
        tenant_id: str,
        entity_id: str,
        override_type: str,
        *,
        scope_key: str = "",
        analyst_rationale: str = "",
    ) -> str:
        """Closed loop: analyst HIL decision calibrates next automated iteration."""
        return trend_store.insert_hil_override(
            tenant_id=tenant_id,
            entity_id=entity_id,
            override_type=override_type,
            scope_key=scope_key,
            analyst_rationale=analyst_rationale,
        )


async def run_trend_evaluation(
    tenant_id: str,
    entity_id: str,
    *,
    region_code: str = "",
    window_rows: list[dict[str, Any]] | None = None,
    skip_llm: bool | None = None,
) -> dict[str, Any]:
    skip = (
        bool(skip_llm)
        if skip_llm is not None
        else (os.environ.get("TREND_AGENT_SKIP_LLM") or "").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    llm: LlmClient | None = None if skip else OpenAICompatibleJsonClient()
    agent = TrendAgent(llm=llm, skip_llm=skip)
    return await agent.run_evaluation_loop(
        tenant_id=tenant_id,
        entity_id=entity_id,
        region_code=region_code,
        window_rows=window_rows,
    )
