"""Gate: ``FraudAnalystPrompt.build`` interpolates ``TransactionSchema`` and demands ``ShadowDecision`` JSON."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

_SRC_SHADOW = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
for _p in (_SRC_SHADOW, _SRC_INGESTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from ingestor.schemas import TransactionSchema  # noqa: E402
from shadow_agent.history import RecentEntityTransaction  # noqa: E402
from shadow_agent.prompts import (  # noqa: E402
    PROMPT_CHAR_BUDGET,
    FraudAnalystPrompt,
)


def test_fraud_analyst_prompt_print_and_interpolation(capsys) -> None:
    tx = TransactionSchema(
        entity_id=UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
        amount=199.99,
        timestamp=datetime(2026, 1, 15, 12, 30, 45, tzinfo=UTC),
        metadata={"channel": "card_not_present", "mcc": "5411"},
    )
    text = FraudAnalystPrompt.build(tx)
    print(text, end="")
    out = capsys.readouterr().out
    assert out == text

    assert "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" in text
    assert repr(199.99) in text
    assert "2026-01-15T12:30:45" in text
    assert "channel" in text and "card_not_present" in text
    assert "mcc" in text and "5411" in text

    assert "ShadowDecision" in text or "transaction_id" in text
    assert "risk_score" in text
    assert "no markdown" in text.lower() or "markdown" in text.lower()
    assert "JSON object" in text

    meta_line = [ln for ln in text.splitlines() if ln.strip().startswith("- metadata")][0]
    embedded = meta_line.split(":", 1)[1].strip()
    assert json.loads(embedded) == {"channel": "card_not_present", "mcc": "5411"}


def test_fraud_analyst_prompt_print_history_json_injected(capsys) -> None:
    """Gate: built prompt prints with ``Entity History`` JSON array and velocity guidance."""
    tx = TransactionSchema(
        entity_id=UUID("11111111-2222-3333-4444-555555555555"),
        amount=50.0,
        timestamp=datetime(2026, 4, 1, 9, 0, 0, tzinfo=UTC),
        metadata={"channel": "wire"},
    )
    history = [
        RecentEntityTransaction(
            timestamp=datetime(2026, 3, 1, 9, 0, 0, tzinfo=UTC),
            amount=25.0,
            is_fraud=False,
        ),
        RecentEntityTransaction(
            timestamp=datetime(2026, 3, 15, 9, 0, 0, tzinfo=UTC),
            amount=40.0,
            is_fraud=True,
        ),
    ]
    text = FraudAnalystPrompt.build(tx, history_records=history)
    print(text, end="")
    out = capsys.readouterr().out
    assert out == text

    assert "Entity History: " in text
    assert ". Consider velocity and previous fraud flags." in text
    marker = "Entity History: "
    start = text.index(marker) + len(marker)
    end = text.index(". Consider velocity and previous fraud flags.", start)
    embedded = text[start:end]
    arr = json.loads(embedded)
    assert arr == [
        {"timestamp": "2026-03-01T09:00:00+00:00", "amount": 25.0, "is_fraud": False},
        {"timestamp": "2026-03-15T09:00:00+00:00", "amount": 40.0, "is_fraud": True},
    ]
    assert len(text) <= PROMPT_CHAR_BUDGET


def test_fraud_analyst_prompt_history_truncates_when_over_budget(monkeypatch) -> None:
    tx = TransactionSchema(
        entity_id=UUID("99999999-9999-9999-9999-999999999999"),
        amount=1.0,
        timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        metadata={},
    )
    many = [
        RecentEntityTransaction(
            timestamp=datetime(2026, 1, 1, 0, 0, i, tzinfo=UTC),
            amount=float(i),
            is_fraud=i % 2 == 0,
        )
        for i in range(40)
    ]
    monkeypatch.setattr("shadow_agent.prompts.PROMPT_CHAR_BUDGET", 2200)
    text = FraudAnalystPrompt.build(tx, history_records=many)
    assert len(text) <= 2200
    assert "Entity History: " in text
    start = text.index("Entity History: ") + len("Entity History: ")
    end = text.index(". Consider velocity and previous fraud flags.", start)
    arr = json.loads(text[start:end])
    assert isinstance(arr, list)
    assert len(arr) < len(many)
    assert len(arr) >= 1
