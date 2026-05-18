"""Shadow agent: structured LLM decisions (provider path) and forensic evaluate path (HTTP client)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx
from ingestor.schemas import TransactionSchema
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from shadow_agent.friendly_fraud import (
    apply_friendly_fraud_post_rules,
    build_friendly_fraud_signals,
)
from shadow_agent.graph_hints import listing_id_from_transaction
from shadow_agent.graph_tool import (
    find_linked_entities,
    neo4j_driver_from_env,
    should_invoke_find_linked_entities,
    wants_find_linked_entities,
)
from shadow_agent.history import get_recent_entity_transactions
from shadow_agent.llm_client import OllamaLLMClient
from shadow_agent.prompt_sanitize import sanitize_transaction_for_prompt
from shadow_agent.prompts import FraudAnalystPrompt
from shadow_agent.providers.base import BaseLLMProvider
from shadow_agent.review_integrity_tool import (
    check_review_integrity,
    should_invoke_check_review_integrity,
    wants_check_review_integrity,
)
from shadow_agent.scout_coordinated_burst import (
    run_scout_coordinated_burst_probe,
    wants_scout_coordinated_burst,
)
from shadow_agent.schemas import ShadowDecision
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from tarka_shared.audit_trail import AuditLog, Case
from tarka_shared.case_status import DEFAULT_CASE_STATUS
from tarka_shared.data.tenant_constants import DEFAULT_TENANT_ID

logger = logging.getLogger(__name__)

_OLLAMA_TIMEOUT_TYPES = (
    httpx.ReadTimeout,
    httpx.ConnectTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
)


async def _ensure_case_for_shadow_audit(session: AsyncSession, case_id: str) -> None:
    """Ensure a ``cases`` row exists so ``audit_logs.case_id`` FK can succeed."""
    existing = await session.scalar(select(Case).where(Case.id == case_id))
    if existing is not None:
        return
    session.add(
        Case(
            id=case_id,
            tenant_id=DEFAULT_TENANT_ID,
            name="shadow-sidecar-transaction-anchor",
            dataset_path=None,
            is_active=False,
            status=DEFAULT_CASE_STATUS,
        )
    )
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        retry = await session.scalar(select(Case).where(Case.id == case_id))
        if retry is None:
            raise


class TransactionAnalysis(BaseModel):
    """Structured output for transaction narrative review."""

    model_config = ConfigDict(extra="forbid")

    risk_level: str = Field(..., description="One of LOW, MEDIUM, HIGH")
    rationale: str = Field(..., min_length=1)
    recommended_action: str = Field(..., min_length=1)


class ShadowAgent:
    """
    Orchestrates LLM-backed fraud workflows.

    * ``analyze_transaction`` — uses an injected :class:`~shadow_agent.providers.base.BaseLLMProvider`
      (legacy / tools sidecar).
    * ``evaluate`` — builds a forensic prompt from :class:`~ingestor.schemas.TransactionSchema`,
      calls :class:`~shadow_agent.llm_client.OllamaLLMClient`, and validates :class:`~shadow_agent.schemas.ShadowDecision`.
    """

    def __init__(
        self,
        provider: BaseLLMProvider | None = None,
        *,
        llm_client: OllamaLLMClient | None = None,
    ) -> None:
        if provider is None and llm_client is None:
            raise ValueError("ShadowAgent requires at least one of: provider, llm_client")
        self._provider = provider
        self._llm_client = llm_client

    @property
    def provider_class_name(self) -> str:
        """Concrete provider type name for logs (e.g. ``OllamaProvider`` / ``OpenAIProvider``)."""
        if self._provider is None:
            return "none"
        return self._provider.__class__.__name__

    async def evaluate(
        self,
        tx: TransactionSchema,
        session: AsyncSession,
        *,
        graph_context: dict[str, Any] | None = None,
    ) -> tuple[ShadowDecision, AuditLog]:
        """
        Forensic path: prompt → Ollama ``chat_json_validated`` → :class:`~shadow_agent.schemas.ShadowDecision`.

        Loads prior audit rows for ``tx.entity_id`` via ``await get_recent_entity_transactions`` (same
        session, strictly before the LLM call) so the system prompt always includes up-to-date history;
        a future version could overlap this read with unrelated work using tasks, but ordering here
        is intentionally sequential.

        On ``httpx`` connect/read/write/pool timeouts from the local Ollama client (after its own retry
        policy), returns a deterministic safe decision (``is_fraud=False``, ``risk_score=0``,
        ``reasoning=["TIMEOUT_FALLBACK"]``) and continues persistence so ingestion is not aborted.

        Persists an :class:`~tarka_shared.audit_trail.AuditLog` via ``session.add`` + ``session.commit``.
        If ``commit`` raises :class:`~sqlalchemy.exc.IntegrityError`, the decision is still returned but a
        ``CRITICAL`` log is emitted and the session is rolled back.

        Requires ``llm_client`` to be configured on this agent.
        """
        if self._llm_client is None:
            raise RuntimeError(
                "ShadowAgent.evaluate requires llm_client=OllamaLLMClient in constructor"
            )

        entity_s = str(tx.entity_id)
        logger.info(
            "shadow_evaluate_start entity_id=%s amount=%s",
            entity_s,
            tx.amount,
        )

        # Sequential await (not concurrent) so history is fully loaded before prompt build + Ollama.
        history = await get_recent_entity_transactions(session, entity_s, 5)
        merged_ctx: dict[str, Any] = dict(graph_context) if graph_context else {}
        ff_signals = await build_friendly_fraud_signals(session, tx, graph_context=graph_context)
        _inject_ff = bool(graph_context) or int(ff_signals.get("prior_successful_orders_same_ip") or 0) >= 10 or bool(
            ff_signals.get("delivery_confirmation_hash_seen_in_audit"),
        ) or bool(ff_signals.get("delivery_confirmation_timestamp_aligned_with_dispute"))
        if _inject_ff:
            merged_ctx["friendly_fraud_signals"] = ff_signals
        drv: Any | None = None
        try:
            wants_linked = wants_find_linked_entities(tx, merged_ctx)
            wants_review = wants_check_review_integrity(tx, merged_ctx)
            drv = neo4j_driver_from_env()
            if wants_linked and drv is None:
                logger.warning(
                    "shadow_tool_find_linked_entities_skipped_driver_unavailable entity_id=%s",
                    entity_s,
                )
            if wants_review and drv is None:
                logger.warning(
                    "shadow_tool_check_review_integrity_skipped_driver_unavailable entity_id=%s",
                    entity_s,
                )
            if drv is not None:
                if should_invoke_find_linked_entities(
                    tx,
                    merged_ctx,
                    driver_available=True,
                ):
                    logger.info(
                        "shadow_tool_find_linked_entities entity_id=%s tool=find_linked_entities "
                        "hops=2 graph_probe=shared_ip_2hop",
                        entity_s,
                    )
                    summary = await find_linked_entities(entity_s, tx, drv)
                    merged_ctx["find_linked_entities"] = summary
                    logger.info(
                        "shadow_tool_find_linked_entities_complete entity_id=%s summary_chars=%s",
                        entity_s,
                        len(summary),
                    )
                if should_invoke_check_review_integrity(
                    tx,
                    merged_ctx,
                    driver_available=True,
                ):
                    lid = listing_id_from_transaction(tx)
                    if lid:
                        logger.info(
                            "shadow_tool_check_review_integrity entity_id=%s listing_id=%s",
                            entity_s,
                            lid,
                        )
                        review_payload = await check_review_integrity(lid, drv)
                        merged_ctx["check_review_integrity"] = review_payload
                        logger.info(
                            "shadow_tool_check_review_integrity_complete entity_id=%s "
                            "review_ring_likely=%s reviewers=%s",
                            entity_s,
                            review_payload.get("review_ring_likely"),
                            review_payload.get("reviewer_count"),
                        )
        finally:
            if drv is not None:
                await drv.close()

        if wants_scout_coordinated_burst(merged_ctx):
            logger.info("shadow_scout_coordinated_burst_start entity_id=%s", entity_s)
            scout_payload = run_scout_coordinated_burst_probe()
            merged_ctx["scout_coordinated_bursts"] = scout_payload
            logger.info(
                "shadow_scout_coordinated_burst_complete entity_id=%s bursts_found=%s",
                entity_s,
                scout_payload.get("bursts_found"),
            )

        tx_prompt = sanitize_transaction_for_prompt(tx)
        system_prompt = FraudAnalystPrompt.build(
            tx_prompt,
            history_records=history,
            graph_context=merged_ctx if merged_ctx else None,
        )
        logger.info(
            "shadow_evaluate_prompt_generated entity_id=%s prompt_char_count=%s",
            entity_s,
            len(system_prompt),
        )

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": "Respond with exactly one JSON object as specified. No other text.",
            },
        ]
        raw_prompt_text = json.dumps(messages, ensure_ascii=False)

        t0 = time.perf_counter()
        raw_obj: Any
        try:
            raw_obj = await self._llm_client.chat_json_validated(messages)
        except _OLLAMA_TIMEOUT_TYPES as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            logger.warning(
                "shadow_evaluate_ollama_timeout_fallback entity_id=%s duration_ms=%.2f "
                "exc_type=%s exc=%r",
                entity_s,
                elapsed_ms,
                type(exc).__name__,
                exc,
            )
            decision = ShadowDecision(
                transaction_id=tx.entity_id,
                risk_score=0.0,
                is_fraud=False,
                reasoning=["TIMEOUT_FALLBACK"],
                confidence_metrics={},
                ai_reasoning="TIMEOUT_FALLBACK",
            )
            decision = apply_friendly_fraud_post_rules(decision, ff_signals)
            raw_response_text = json.dumps(
                {
                    "timeout_fallback": True,
                    "ollama_exception": type(exc).__name__,
                },
                ensure_ascii=False,
            )
        else:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            logger.info(
                "shadow_evaluate_llm_complete entity_id=%s duration_ms=%.2f",
                entity_s,
                elapsed_ms,
            )
            try:
                decision = ShadowDecision.model_validate(raw_obj)
            except ValidationError:
                logger.exception(
                    "shadow_evaluate_validation_failed entity_id=%s",
                    entity_s,
                )
                raise
            decision = apply_friendly_fraud_post_rules(decision, ff_signals)
            raw_response_text = json.dumps(raw_obj, ensure_ascii=False, default=str)

        if decision.transaction_id != tx.entity_id:
            logger.warning(
                "shadow_evaluate_transaction_id_mismatch entity_id=%s decision_transaction_id=%s",
                entity_s,
                decision.transaction_id,
            )

        _meta: dict[str, Any] = tx.metadata if isinstance(tx.metadata, dict) else {}
        _inv = _meta.get("investigation_case_number")
        if _inv is None:
            _inv = _meta.get("case_number")
        _outcome_raw = _meta.get("case_outcome")
        _outcome = str(_outcome_raw).strip().upper() if _outcome_raw is not None else "UNKNOWN"
        _device = _meta.get("device_id") if _meta.get("device_id") is not None else _meta.get("deviceId")
        _ip = _meta.get("ip_address") if _meta.get("ip_address") is not None else _meta.get("ipAddress")
        audit_log = AuditLog(
            case_id=str(decision.transaction_id),
            action_taken=json.dumps(
                {
                    "transaction_id": str(decision.transaction_id),
                    "amount": float(tx.amount),
                    "is_fraud": decision.is_fraud,
                    "device_id": _device,
                    "ip_address": _ip,
                    "investigation_case_number": _inv,
                    "case_outcome": _outcome,
                },
                separators=(",", ":"),
                ensure_ascii=False,
                default=str,
            ),
            code_executed=raw_prompt_text,
            agent_notes=raw_response_text,
        )
        logger.info(
            "shadow_evaluate_audit_log_materialized entity_id=%s audit_repr=%r",
            entity_s,
            repr(audit_log),
        )

        try:
            await _ensure_case_for_shadow_audit(session, str(decision.transaction_id))
            session.add(audit_log)
            await session.commit()
        except IntegrityError:
            logger.critical(
                "shadow_evaluate_audit_persist_integrity_error entity_id=%s case_id=%s",
                entity_s,
                audit_log.case_id,
                exc_info=True,
            )
            await session.rollback()
        else:
            await session.refresh(audit_log)

        logger.info(
            "shadow_evaluate_validation_ok entity_id=%s risk_score=%s is_fraud=%s reasoning_count=%s",
            decision.transaction_id,
            decision.risk_score,
            decision.is_fraud,
            len(decision.reasoning),
        )
        return decision, audit_log

    async def analyze_transaction(self, narrative: str) -> TransactionAnalysis:
        """
        Run a full structured analysis of ``narrative`` using the configured LLM backend.

        Logs **provider** identity before and after inference for operational traceability.
        """
        if self._provider is None:
            raise RuntimeError("ShadowAgent.analyze_transaction requires a BaseLLMProvider")

        logger.info(
            "shadow_transaction_analysis_start provider=%s",
            self.provider_class_name,
        )
        prompt = (
            "You are a fraud analyst. Given the transaction narrative below, "
            "produce JSON with keys risk_level (LOW|MEDIUM|HIGH), rationale (string), "
            "recommended_action (string, e.g. APPROVE, HOLD, ESCALATE).\n\n"
            f"NARRATIVE:\n{narrative.strip()}"
        )
        result = await self._provider.generate_decision(prompt, TransactionAnalysis)
        if not isinstance(result, TransactionAnalysis):
            raise TypeError("provider returned unexpected type")
        logger.info(
            "shadow_transaction_analysis_complete provider=%s risk_level=%s",
            self.provider_class_name,
            result.risk_level,
        )
        return result
