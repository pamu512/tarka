"""Gate tests for ``shadow_agent.schemas``."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from shadow_agent.schemas import ShadowDecision  # noqa: E402


def test_shadow_decision_rejects_risk_score_above_100() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ShadowDecision(
            transaction_id=uuid4(),
            risk_score=105.0,
            is_fraud=False,
            reasoning=["manual review"],
            confidence_metrics={"score": 0.5},
        )
    errs = exc_info.value.errors()
    assert any(e.get("loc") == ("risk_score",) for e in errs)
