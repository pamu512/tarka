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
    classify_sop_chunks,
    evidence_is_thin,
    sop_draft_errors,
    validate_ai_authored_pack,
)

logger = logging.getLogger(__name__)


async def author_pack_from_hypothesis(
    report: dict[str, Any],
    llm_client: Any,
    *,
    authored_by: str = "scout",
    model: str | None = None,
    sop_chunks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Send a hypothesis report to the LLM and return a validated observe pack or errors.

    ``llm_client`` must expose ``chat_json_validated(messages, model=...)``
    (the existing in-VPC ``OllamaClient`` / ``OpenAICompatClient``). SOP/OKF
    text is appended on that same call. There is no separate hosted endpoint.

    ``sop_chunks=None`` leaves SOP missing. A provided list that is empty,
    thin, or unallowlisted abstains and does not invent a desk rule.

    Returns ``{"ok": True, "pack": {...}}`` or ``{"ok": False, "errors": [...]}``.
    Abstained results omit ``pack``.
    """
    if evidence_is_thin(report):
        return {"ok": False, "errors": ["thin_evidence"], "abstained": True}

    allowlisted: list[dict[str, str]] = []
    if sop_chunks is not None:
        classified = classify_sop_chunks(sop_chunks)
        if classified["state"] != "ready":
            return {"ok": False, "errors": ["sop_missing"], "abstained": True}
        allowlisted = classified["allowlisted"]

    directive = build_llm_directive()
    report_json = json.dumps(report, indent=2, default=str, ensure_ascii=False)
    user = (
        f"Hypothesis report from {authored_by}:\n\n"
        f"```json\n{report_json}\n```\n\n"
        "Based on this report, produce exactly one JSON rule pack "
        "that conforms to the contract above. "
        f'Set authored_by to "{authored_by}". '
        "If the evidence is insufficient to justify a rule, "
        'respond with {"ok": false, "reason": "insufficient_evidence"}. '
        "Do not invent rules without supporting evidence. "
        "Drafts stay mode shadow. Do not Promote, ALLOW, or DENY."
    )
    if allowlisted:
        user += (
            "\n\nAllowlisted tenant SOP/OKF chunks. Cite ids in evidence only. "
            "Do not copy chunk text into when.value or score_delta. "
            "Do not invent desk rules the chunks do not state.\n"
            + json.dumps(allowlisted, ensure_ascii=False)
        )
        logger.info(
            "pack_author_sop_chunks ids=%s",
            [row["id"] for row in allowlisted],
        )

    messages = [
        {
            "role": "system",
            "content": directive,
        },
        {
            "role": "user",
            "content": user,
        },
    ]

    try:
        raw = await llm_client.chat_json_validated(messages, model=model)
    except Exception:
        logger.warning("pack_author_llm_call_failed", exc_info=True)
        return {"ok": False, "errors": ["llm_call_failed"]}

    if not isinstance(raw, dict):
        return {"ok": False, "errors": ["llm_response_not_object"]}

    # LLM explicitly declined (insufficient evidence)
    if raw.get("ok") is False:
        reason = raw.get("reason", "llm_declined")
        logger.info("pack_author_llm_declined: %s", reason)
        return {"ok": False, "errors": [f"llm_declined: {reason}"]}

    checked = validate_ai_authored_pack(raw)
    if not checked["ok"]:
        return checked
    extra = sop_draft_errors(checked["pack"], sop_chunks)
    if extra:
        return {"ok": False, "errors": extra}
    return checked
