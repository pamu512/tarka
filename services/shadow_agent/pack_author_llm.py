"""Thin LLM bridge: send the pack-author directive + schema, parse + validate response.

Requires ``SHADOW_LLM_BACKEND`` + ``SHADOW_LLM_BASE_URL`` (for self-hosted/vllm).
Production refuses public api.openai.com (enforced by llm_client).

Usage::

    from pack_author_llm import author_pack_from_hypothesis
    result = await author_pack_from_hypothesis(report_dict, llm_client)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pack_author_contract import (
    build_llm_directive,
    validate_ai_authored_pack,
)

logger = logging.getLogger(__name__)


async def author_pack_from_hypothesis(
    report: dict[str, Any],
    llm_client: Any,
    *,
    authored_by: str = "scout",
    model: str | None = None,
) -> dict[str, Any]:
    """Send a hypothesis report to the LLM and return a validated pack or errors.

    ``llm_client`` must expose ``chat_json_validated(messages, model=...)``
    (the existing ``OllamaClient`` / ``OpenAICompatClient``).

    Returns ``{"ok": True, "pack": {...}}`` or ``{"ok": False, "errors": [...]}``.
    """
    directive = build_llm_directive()

    report_json = json.dumps(report, indent=2, default=str, ensure_ascii=False)

    messages = [
        {
            "role": "system",
            "content": directive,
        },
        {
            "role": "user",
            "content": (
                f"Hypothesis report from {authored_by}:\n\n"
                f"```json\n{report_json}\n```\n\n"
                "Based on this report, produce exactly one JSON rule pack "
                "that conforms to the contract above. "
                f'Set authored_by to "{authored_by}". '
                "If the evidence is insufficient, respond with a minimal "
                "pack containing one conservative rule."
            ),
        },
    ]

    try:
        raw = await llm_client.chat_json_validated(messages, model=model)
    except Exception as exc:
        logger.warning("pack_author_llm_call_failed: %s", exc)
        return {"ok": False, "errors": [f"llm_call_failed: {exc}"]}

    if not isinstance(raw, dict):
        return {"ok": False, "errors": ["llm_response_not_object"]}

    return validate_ai_authored_pack(raw)
