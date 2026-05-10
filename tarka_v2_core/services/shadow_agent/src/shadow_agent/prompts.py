"""LLM system prompts built from ingestion contracts."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Final

from ingestor.schemas import TransactionSchema
from shadow_agent.history import RecentEntityTransaction
from shadow_agent.schemas import ShadowDecision

_JSON_SCHEMA_SPEC: Final[str] = json.dumps(
    ShadowDecision.model_json_schema(),
    separators=(",", ":"),
    ensure_ascii=False,
)

# Heuristic: ~4 characters per token for English + JSON-heavy prompts (conservative lower bound).
_ASSUMED_CONTEXT_WINDOW_TOKENS: Final[int] = 4096
_CHARS_PER_TOKEN_HEURISTIC: Final[int] = 4
PROMPT_CHAR_BUDGET: Final[int] = _ASSUMED_CONTEXT_WINDOW_TOKENS * _CHARS_PER_TOKEN_HEURISTIC

_HISTORY_PREFIX: Final[str] = "\n\nEntity History: "
_HISTORY_SUFFIX: Final[str] = ". Consider velocity and previous fraud flags."


def _core_prompt(tx: TransactionSchema) -> str:
    entity_id = str(tx.entity_id)
    amount_repr = repr(tx.amount)
    timestamp_iso = tx.timestamp.isoformat()
    metadata_json = json.dumps(tx.metadata, sort_keys=True, ensure_ascii=False)

    return (
        "You are a senior forensic fraud auditor working under adversarial review. "
        "Treat every field as evidence-grade: be conservative, cite concrete facts "
        "from the transaction, and separate calibrated risk from narrative reasoning.\n\n"
        "TRANSACTION UNDER REVIEW (verbatim facts; do not invent fields):\n"
        f"- entity_id (canonical transaction id for this case): {entity_id}\n"
        f"- amount: {amount_repr}\n"
        f"- timestamp (ISO 8601): {timestamp_iso}\n"
        f"- metadata (JSON object): {metadata_json}\n\n"
        "OUTPUT CONTRACT — NON-NEGOTIABLE:\n"
        "1. Your entire reply MUST be exactly one JSON object and nothing else.\n"
        "2. Do not wrap the JSON in markdown, backticks, or commentary.\n"
        "3. The JSON MUST validate against this Pydantic v2 JSON Schema for "
        "`ShadowDecision` (types, required keys, and numeric bounds are mandatory):\n"
        f"{_JSON_SCHEMA_SPEC}\n"
        "4. Set `transaction_id` to the UUID string shown above as entity_id "
        "(same value as this transaction's entity_id).\n"
        "5. `risk_score` MUST be a number between 0 and 100 inclusive.\n"
        "6. `reasoning` MUST be a JSON array of non-empty forensic strings grounded "
        "in the supplied transaction.\n"
        "7. `confidence_metrics` MUST be a JSON object whose keys are metric names "
        "and values are JSON-serializable (numbers recommended where applicable).\n"
    )


def _history_payload_dicts(records: Sequence[RecentEntityTransaction]) -> list[dict[str, object]]:
    return [
        {
            "timestamp": r.timestamp.isoformat(),
            "amount": r.amount,
            "is_fraud": r.is_fraud,
        }
        for r in records
    ]


def _history_section(
    core_len: int, records: Sequence[RecentEntityTransaction], char_budget: int
) -> str:
    """Build ``Entity History: …`` suffix, dropping trailing (oldest) rows until within ``char_budget``."""
    min_suffix = len(_HISTORY_PREFIX) + len("[]") + len(_HISTORY_SUFFIX)
    if core_len + min_suffix > char_budget:
        return ""

    working = list(records)
    while True:
        history_json = json.dumps(
            _history_payload_dicts(working),
            separators=(",", ":"),
            ensure_ascii=False,
        )
        section = f"{_HISTORY_PREFIX}{history_json}{_HISTORY_SUFFIX}"
        if core_len + len(section) <= char_budget:
            return section
        if len(working) <= 1:
            # Single row still overflows: emit a minimal object so JSON stays valid.
            if not working:
                return f"{_HISTORY_PREFIX}[]{_HISTORY_SUFFIX}"
            r0 = working[0]
            tiny = json.dumps(
                [{"amount": r0.amount, "is_fraud": r0.is_fraud}],
                separators=(",", ":"),
                ensure_ascii=False,
            )
            tiny_section = f"{_HISTORY_PREFIX}{tiny}{_HISTORY_SUFFIX}"
            if core_len + len(tiny_section) <= char_budget:
                return tiny_section
            bare = json.dumps(
                [{"is_fraud": r0.is_fraud}], separators=(",", ":"), ensure_ascii=False
            )
            bare_section = f"{_HISTORY_PREFIX}{bare}{_HISTORY_SUFFIX}"
            if core_len + len(bare_section) <= char_budget:
                return bare_section
            return f"{_HISTORY_PREFIX}[]{_HISTORY_SUFFIX}"
        working.pop()


class FraudAnalystPrompt:
    """Builds a strict system prompt for a local Ollama-style forensic fraud audit."""

    @staticmethod
    def build(
        tx: TransactionSchema,
        history_records: Sequence[RecentEntityTransaction] | None = None,
    ) -> str:
        """Return a single plain-text system prompt (no markdown fences).

        The model is instructed to emit **only** a raw JSON object matching
        :class:`~shadow_agent.schemas.ShadowDecision`, with no prose, no markdown,
        and no code fences before or after the JSON.

        When ``history_records`` is not ``None``, an **Entity History** section is appended
        (JSON array of prior ``timestamp`` / ``amount`` / ``is_fraud``). The combined prompt
        is capped at :data:`PROMPT_CHAR_BUDGET` characters (~:data:`_ASSUMED_CONTEXT_WINDOW_TOKENS`
        tokens using a fixed chars/token heuristic); older trailing rows are dropped first.
        """
        core = _core_prompt(tx)
        if history_records is None:
            return core
        suffix = _history_section(len(core), history_records, PROMPT_CHAR_BUDGET)
        return core + suffix
