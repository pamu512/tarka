"""Gate (Prompt 130): Shadow forensic system prompt requires UNKNOWN when facts are absent (no fabrication)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from ingestor.schemas import TransactionSchema
from shadow_agent.prompts import FraudAnalystPrompt


def test_fraud_analyst_prompt_includes_unknown_and_no_fabrication_rule() -> None:
    tx = TransactionSchema(
        entity_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        amount=1.0,
        timestamp=datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC),
        metadata={"ip": "203.0.113.55"},
    )
    prompt = FraudAnalystPrompt.build(tx)
    low = prompt.lower()
    assert "unknown" in low
    assert "fabricat" in low
