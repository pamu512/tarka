"""OpenAI provider: mocked SDK responses → Pydantic ``model_validate``."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel, Field

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from shadow_agent.providers.openai_provider import OpenAIProvider  # noqa: E402


class _RiskDecision(BaseModel):
    verdict: str = Field(..., min_length=1)
    score: float = Field(..., ge=0.0, le=1.0)


def _mock_completion_json(content_obj: dict) -> MagicMock:
    msg = MagicMock()
    msg.content = json.dumps(content_obj)
    msg.refusal = None
    choice = MagicMock(message=msg)
    completion = MagicMock()
    completion.choices = [choice]
    return completion


def test_openai_provider_maps_mocked_json_to_pydantic_json_schema_path() -> None:
    """Structured Outputs path: model ``gpt-4o-mini`` → ``response_format.type == json_schema``."""

    async def _run() -> _RiskDecision:
        completion = _mock_completion_json({"verdict": "APPROVE", "score": 0.42})
        mock_create = AsyncMock(return_value=completion)

        mock_client = MagicMock()
        mock_client.chat = MagicMock()
        mock_client.chat.completions = MagicMock()
        mock_client.chat.completions.create = mock_create

        provider = OpenAIProvider(
            model="gpt-4o-mini",
            client=mock_client,
            api_key="sk-test",
            max_json_retries=2,
        )
        try:
            out = await provider.generate_decision(
                "Return a risk verdict for transaction T-1.",
                _RiskDecision,
            )
        finally:
            await provider.aclose()

        assert mock_create.await_count >= 1
        call_kw = mock_create.await_args.kwargs
        assert call_kw["response_format"]["type"] == "json_schema"
        assert call_kw["response_format"]["json_schema"]["name"] == "_RiskDecision"
        assert call_kw["response_format"]["json_schema"]["strict"] is True
        assert "schema" in call_kw["response_format"]["json_schema"]

        return out

    out = asyncio.run(_run())
    assert isinstance(out, _RiskDecision)
    assert out.verdict == "APPROVE"
    assert out.score == pytest.approx(0.42)


def test_openai_provider_json_object_mode_for_legacy_model() -> None:
    """JSON-object path: legacy model name → ``response_format.type == json_object``."""

    async def _run() -> _RiskDecision:
        completion = _mock_completion_json({"verdict": "REVIEW", "score": 0.88})
        mock_create = AsyncMock(return_value=completion)
        mock_client = MagicMock()
        mock_client.chat = MagicMock()
        mock_client.chat.completions = MagicMock()
        mock_client.chat.completions.create = mock_create

        provider = OpenAIProvider(
            model="gpt-3.5-turbo",
            client=mock_client,
            api_key="sk-test",
        )
        try:
            out = await provider.generate_decision("decide", _RiskDecision)
        finally:
            await provider.aclose()

        rf = mock_create.await_args.kwargs["response_format"]
        assert rf["type"] == "json_object"
        assert isinstance(out, _RiskDecision)
        assert out.verdict == "REVIEW"
        return out

    asyncio.run(_run())
