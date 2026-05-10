"""ShadowAgent DI and logging."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from shadow_agent.agent import ShadowAgent, TransactionAnalysis  # noqa: E402
from shadow_agent.providers.base import BaseLLMProvider  # noqa: E402


class _StubOllamaLikeProvider(BaseLLMProvider):
    async def generate_decision(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        assert schema is TransactionAnalysis
        return TransactionAnalysis(
            risk_level="LOW",
            rationale="stub",
            recommended_action="APPROVE",
        )


def test_shadow_agent_logs_provider_name(caplog: pytest.LogCaptureFixture) -> None:
    async def _run() -> None:
        caplog.set_level(logging.INFO)
        agent = ShadowAgent(provider=_StubOllamaLikeProvider())
        await agent.analyze_transaction("Wire $50 to merchant M.")

    asyncio.run(_run())
    joined = " ".join(rec.message for rec in caplog.records)
    assert "_StubOllamaLikeProvider" in joined
    assert any("shadow_transaction_analysis_start" in r.message for r in caplog.records)
    assert any("shadow_transaction_analysis_complete" in r.message for r in caplog.records)
