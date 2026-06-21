"""Gate: retroactive structural tag extraction via local LLM."""

from __future__ import annotations

from typing import Any

import pytest
from llm_client import ShadowLLMError
from retroactive_label import (
    build_forensic_taxonomy_system_prompt,
    build_retroactive_label_system_prompt,
    evaluate_retroactive,
    evaluate_retroactive_label,
    parse_retroactive_tags,
)


def test_build_forensic_taxonomy_system_prompt_requires_json_array_only() -> None:
    prompt = build_forensic_taxonomy_system_prompt(
        manifest={
            "manifest_id": "m-1",
            "trace_steps": [{"rule_id": "velocity_ip", "matched": True}],
            "transaction": {"entity_id": "e-1", "amount": 10.0},
        },
        context={
            "ground_truth_class": "FRAUD",
            "disposition_text": "Chargeback reason 4853 — account takeover suspected",
        },
    )
    assert "forensic taxonomy extractor" in prompt
    assert "JSON array" in prompt
    assert "compromise_point:pos" in prompt
    assert "fraud_vector:card_pool_velocity" in prompt
    assert "4853" in prompt
    assert "velocity_ip" in prompt


def test_build_retroactive_label_system_prompt_requires_json_array_only() -> None:
    prompt = build_retroactive_label_system_prompt(
        manifest_payload={
            "manifest_id": "m-1",
            "trace_steps": [{"rule_id": "velocity_ip", "matched": True}],
            "transaction": {"entity_id": "e-1", "amount": 10.0},
        },
        feedback_context={
            "ground_truth_class": "FRAUD",
            "disposition_text": "Chargeback reason 4853 — account takeover suspected",
        },
    )
    assert "forensic taxonomy extractor" in prompt
    assert "JSON array" in prompt
    assert "compromise_point:pos" in prompt
    assert "fraud_vector:card_pool_velocity" in prompt


def test_parse_retroactive_tags_normalizes_and_deduplicates() -> None:
    tags = parse_retroactive_tags(
        [
            "Vector:Account_Takeover",
            "vector:account_takeover",
            "compromise_point:pos",
        ],
    )
    assert tags == ["vector:account_takeover", "compromise_point:pos"]


def test_parse_retroactive_tags_rejects_non_array() -> None:
    with pytest.raises(ValueError, match="JSON array"):
        parse_retroactive_tags({"tags": ["vector:account_takeover"]})


@pytest.mark.asyncio
async def test_evaluate_retroactive_returns_validated_tags() -> None:
    class _StubLlm:
        async def chat_json_validated(
            self,
            messages: list[dict[str, str]],
            *,
            model: str | None = None,
            json_self_correction_retries: int = 2,
        ) -> list[str]:
            assert json_self_correction_retries == 0
            system = next(m["content"] for m in messages if m.get("role") == "system")
            assert "4853" in system
            assert "trace_steps" in system
            assert "forensic taxonomy extractor" in system
            return ["vector:ato", "velocity:card_pool"]

    tags = await evaluate_retroactive(
        {
            "manifest_id": "m-2",
            "trace_steps": [{"rule_id": "velocity_ip", "matched": True}],
        },
        {
            "ground_truth_class": "FRAUD",
            "disposition_text": "Chargeback 4853 account takeover at POS",
        },
        llm_client=_StubLlm(),  # type: ignore[arg-type]
    )
    assert tags == ["vector:ato", "velocity:card_pool"]


@pytest.mark.asyncio
async def test_evaluate_retroactive_label_returns_validated_tags() -> None:
    class _StubLlm:
        async def chat_json_validated(
            self,
            messages: list[dict[str, str]],
            *,
            model: str | None = None,
            json_self_correction_retries: int = 2,
        ) -> list[str]:
            assert json_self_correction_retries == 0
            system = next(m["content"] for m in messages if m.get("role") == "system")
            assert "4853" in system
            assert "trace_steps" in system
            return ["vector:account_takeover", "compromise_point:pos"]

    tags = await evaluate_retroactive_label(
        {
            "manifest_id": "m-2",
            "trace_steps": [{"rule_id": "velocity_ip", "matched": True}],
        },
        {
            "ground_truth_class": "FRAUD",
            "disposition_text": "Chargeback 4853 account takeover at POS",
        },
        llm_client=_StubLlm(),  # type: ignore[arg-type]
    )
    assert tags == ["vector:account_takeover", "compromise_point:pos"]


@pytest.mark.asyncio
async def test_evaluate_retroactive_label_raises_on_invalid_model_shape() -> None:
    class _BadLlm:
        async def chat_json_validated(self, *args: object, **kwargs: object) -> dict[str, Any]:
            return {"tags": ["vector:account_takeover"]}

    with pytest.raises(ShadowLLMError, match="tag validation"):
        await evaluate_retroactive_label(
            {"trace_steps": []},
            {"disposition_text": "fraud"},
            llm_client=_BadLlm(),  # type: ignore[arg-type]
        )


def test_shadow_runtime_evaluate_retroactive() -> None:
    from main import ShadowRuntime

    class _StubLlm:
        async def chat_json_validated(
            self,
            messages: list[dict[str, str]],
            *,
            model: str | None = None,
            json_self_correction_retries: int = 2,
        ) -> list[str]:
            return ["vector:ato", "signal:chargeback_4853"]

    async def _run() -> None:
        runtime = ShadowRuntime(_StubLlm())  # type: ignore[arg-type]
        tags = await runtime.evaluate_retroactive(
            {"trace_steps": [{"rule_id": "velocity_ip", "matched": True}]},
            {"disposition_text": "4853 account takeover"},
        )
        assert tags == ["vector:ato", "signal:chargeback_4853"]

    import asyncio

    asyncio.run(_run())


def test_internal_retroactive_label_endpoint() -> None:
    from agent import ShadowAgent
    from main import build_app
    from starlette.testclient import TestClient

    class _StubLlm:
        async def chat_json_validated(
            self,
            messages: list[dict[str, str]],
            *,
            model: str | None = None,
            json_self_correction_retries: int = 2,
        ) -> list[str]:
            return ["vector:account_takeover", "signal:chargeback_4853"]

    app = build_app(
        shadow_agent=ShadowAgent(llm_client=_StubLlm()),  # type: ignore[arg-type]
        shadow_api_key="retro-label-test-key",
    )

    with TestClient(app) as client:
        r = client.post(
            "/internal/v1/retroactive-label/evaluate",
            headers={"X-Shadow-Token": "retro-label-test-key"},
            json={
                "manifest_payload": {
                    "manifest_id": "m-3",
                    "trace_steps": [{"rule_id": "velocity_ip", "matched": True}],
                },
                "feedback_context": {
                    "ground_truth_class": "FRAUD",
                    "disposition_text": "4853 account takeover",
                },
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["tags"] == ["vector:account_takeover", "signal:chargeback_4853"]
