"""LLM system prompts built from ingestion contracts."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Final

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

_GRAPH_TOPOLOGY_INSTRUCTIONS: Final[str] = (
    "You are also provided with Graph Topology signals. If an entity has a High Degree Centrality "
    "or belongs to a known 'Fraud Cluster' (shared hardware with 3+ blocked accounts), weigh this "
    "heavily in your reasoning. When ``device_hardware_graph.linked_to_blocked_node`` is true, you "
    "MUST include the exact phrase **Linked to Blocked Node** in your ``ai_reasoning`` string and "
    "reflect that linkage in ``risk_score`` / ``is_fraud`` as appropriate.\n\n"
    "When the key ``find_linked_entities`` is present, it is a **trusted graph-tool summary** "
    "(2-hop neighborhood plus shared IP / ORDERED_FROM_IP linkage). Use it before finalizing "
    "borderline decisions; cite shared IP history in ``ai_reasoning`` when it materially affects risk.\n\n"
    "When ``check_review_integrity`` is present, it is a **trusted review-ring probe** for the "
    "listing in metadata: same-listing reviewers who share ``Device`` / ``IP`` nodes (graph topology) "
    "plus optional DuckDB signup burst. For questions about whether reviews look **organic**, "
    "cite ``risk_summary`` and ``review_ring_likely``; mention shared hardware or IP explicitly when "
    "``reviewers_sharing_device_or_ip_count`` is 2 or higher.\n\n"
    "When ``scout_coordinated_bursts`` is present, it is a **trusted DuckDB Scout** probe for "
    "**coordinated hardware bursts**: more than five distinct ``acc_id`` values sharing the same "
    "``canvas_hash`` or ``webgl_vendor`` inside a four-hour window on ``raw_signals``. For each "
    "entry in ``hypothesis_reports``, cite ``narrative``, ``fingerprint_kind``, "
    "``distinct_account_count``, and ``confidence`` in ``ai_reasoning``; when bursts are found, "
    "elevate ``risk_score`` / ``is_fraud`` unless contradictory transaction facts exist. "
    "Reference ``suggested_rule`` only as a hypothesis—not as deployed policy. "
    "Prefer ``saarthi_narrative`` (two-sentence Saarthi summary) in ``ai_reasoning`` when present. "
    "Only treat bursts with ``analyst_suggestion_allowed: true`` as promotion-ready—entries blocked "
    "by the 7-day DuckDB backtest (FPR ≥ 0.1%) must not be escalated to analysts.\n\n"
)
_GRAPH_CONTEXT_PREFIX: Final[str] = "GRAPH CONTEXT (trusted infrastructure JSON):\n"

_FRIENDLY_FRAUD_INSTRUCTIONS: Final[str] = (
    "\n\nFRIENDLY FRAUD / DISPUTE EVIDENCE:\n"
    "The JSON may include ``friendly_fraud_signals``. When "
    "``prior_successful_orders_same_ip`` is **greater than or equal to 10**, the shopper has "
    "material prior **successful** fulfillment history from the same ``anchor_ip_address``—weigh "
    "**chargeback / first-party misuse** narratives as potential **friendly fraud** unless "
    "contradicted by hard evidence. When ``delivery_confirmation_timestamp_aligned_with_dispute`` "
    "is true, a **delivery confirmation** hash recorded in ``audit_logs`` aligns with the dispute "
    "timestamp window—cite that explicitly in ``ai_reasoning``. When you adopt a friendly-fraud "
    "disposition, set ``confidence_metrics.dispute_classification`` to the string **FRIENDLY_FRAUD** "
    "so automation can consume it.\n"
)

_CLUSTER_ANALYSIS_INSTRUCTIONS: Final[str] = (
    "\n\nKNOWLEDGE DROP — CLUSTER COORDINATION:\n"
    "When ``two_hop_network`` and/or ``duck_spend_velocity_30d`` appear in GRAPH CONTEXT, add a clearly "
    "labeled **Cluster Analysis** section inside ``ai_reasoning``. That section MUST cite concrete evidence "
    "from ``two_hop_network`` (e.g. neighbor users, ``blocked_device_touch_count``, edge summaries) AND "
    "from ``duck_spend_velocity_30d`` (e.g. ``total_spend_window``, ``spend_last_2h``, "
    "``spike_pct_vs_flat_baseline_2h``). Follow ``cluster_analyst_instruction`` for the dispute framing. "
    "Do not invent metrics absent from the JSON.\n"
)


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
        "8. `ai_reasoning` MUST be non-empty; when GRAPH CONTEXT appears below, cite topology there "
        "(including **Linked to Blocked Node** when flagged).\n"
        "9. **Evidence integrity:** Never fabricate graph metrics, IP intelligence, counts, or metadata keys absent "
        "from the TRANSACTION block or GRAPH CONTEXT JSON. If a fact is missing or a subgraph is empty, say so "
        "explicitly using the literal **UNKNOWN** for that attribute (e.g. in `ai_reasoning` or string-valued "
        "`confidence_metrics`)—do not substitute invented values.\n"
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


def _graph_context_block(graph_context: dict[str, Any], *, room: int) -> str:
    if room <= 0 or not graph_context:
        return ""
    body = _GRAPH_TOPOLOGY_INSTRUCTIONS
    if graph_context.get("two_hop_network") is not None or graph_context.get("duck_spend_velocity_30d"):
        body = body + _CLUSTER_ANALYSIS_INSTRUCTIONS
    if graph_context.get("friendly_fraud_signals") is not None:
        body = body + _FRIENDLY_FRAUD_INSTRUCTIONS
    body = body + _GRAPH_CONTEXT_PREFIX
    payload = json.dumps(graph_context, separators=(",", ":"), ensure_ascii=False)
    block = body + payload + "\n"
    if len(block) > room:
        keep = max(0, room - len(body) - 2)
        block = body + (payload[:keep] if keep > 0 else "") + "…\n"
    return block


class FraudAnalystPrompt:
    """Builds a strict system prompt for a local Ollama-style forensic fraud audit."""

    @staticmethod
    def build(
        tx: TransactionSchema,
        history_records: Sequence[RecentEntityTransaction] | None = None,
        *,
        graph_context: dict[str, Any] | None = None,
    ) -> str:
        """Return a single plain-text system prompt (no markdown fences).

        The model is instructed to emit **only** a raw JSON object matching
        :class:`~shadow_agent.schemas.ShadowDecision`, with no prose, no markdown,
        and no code fences before or after the JSON.

        When ``graph_context`` is not ``None``, a **GRAPH CONTEXT** section is inserted after the
        core contract (bounded by :data:`PROMPT_CHAR_BUDGET`).

        When ``history_records`` is not ``None``, an **Entity History** section is appended
        (JSON array of prior ``timestamp`` / ``amount`` / ``is_fraud``). The combined prompt
        is capped at :data:`PROMPT_CHAR_BUDGET` characters (~:data:`_ASSUMED_CONTEXT_WINDOW_TOKENS`
        tokens using a fixed chars/token heuristic); older trailing rows are dropped first.
        """
        core = _core_prompt(tx)
        graph_room = PROMPT_CHAR_BUDGET - len(core) - 120
        graph_block = (
            _graph_context_block(graph_context, room=max(0, graph_room))
            if graph_context
            else ""
        )
        merged = core + graph_block
        if history_records is None:
            return merged[:PROMPT_CHAR_BUDGET]
        suffix = _history_section(len(merged), history_records, PROMPT_CHAR_BUDGET)
        return (merged + suffix)[:PROMPT_CHAR_BUDGET]
