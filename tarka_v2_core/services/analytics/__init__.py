"""V2 analytics workers (macro seasonal synthesis, RAG context)."""

from macro_synthesizer import (
    ClickHouseConnectionExhaustedError,
    MacroSynthesizer,
    MacroSynthesizerConfig,
    MacroSynthesizerError,
    RagContextMatrix,
)
from trend_agent import (
    TrendAgent,
    TrendAgentSettings,
    TrendDecisionEnvelope,
    TrendEvaluationResult,
    envelope_action_payload,
    run_trend_evaluation,
    try_resolve_systemic,
)

__all__ = [
    "ClickHouseConnectionExhaustedError",
    "MacroSynthesizer",
    "MacroSynthesizerConfig",
    "MacroSynthesizerError",
    "RagContextMatrix",
    "TrendAgent",
    "TrendAgentSettings",
    "TrendDecisionEnvelope",
    "TrendEvaluationResult",
    "envelope_action_payload",
    "run_trend_evaluation",
    "try_resolve_systemic",
]
