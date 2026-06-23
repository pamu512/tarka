"""Retroactive structural tag extraction from EvidenceManifest + human feedback."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from llm_client import OllamaLLMClient, ShadowLLMError

logger = logging.getLogger(__name__)

_RETROACTIVE_TAG_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z][a-z0-9_]*:[a-z][a-z0-9_]{0,63}$",
)
_MAX_TAGS = 32
_MAX_TAG_LEN = 96


class RetroactiveLabelRequest(BaseModel):
    """Internal API body for retroactive label evaluation."""

    model_config = ConfigDict(extra="forbid")

    manifest_payload: dict[str, Any] = Field(
        ...,
        description="Historic EvidenceManifest projection (trace, signals, transaction context).",
    )
    feedback_context: dict[str, Any] = Field(
        ...,
        description="Analyst/chargeback feedback (disposition text, ground truth, parsed entities).",
    )


def _normalize_manifest_payload(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("manifest_payload must be a JSON object")
    if not raw:
        raise ValueError("manifest_payload must be non-empty")
    return raw


def _normalize_feedback_context(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("feedback_context must be a JSON object")
    if not raw:
        raise ValueError("feedback_context must be non-empty")
    return raw


def _normalize_tag_token(raw: str) -> str:
    token = (raw or "").strip().lower()
    if not token:
        raise ValueError("tag must be non-empty")
    token = token.replace(" ", "_")
    token = token.replace("/", "_")
    if len(token) > _MAX_TAG_LEN:
        token = token[:_MAX_TAG_LEN]
    if not _RETROACTIVE_TAG_RE.fullmatch(token):
        raise ValueError(
            f"tag {token!r} must match namespace:value (e.g. compromise_point:pos)",
        )
    return token


def parse_retroactive_tags(raw: Any) -> list[str]:
    """Validate model output as a deduplicated JSON array of ``namespace:value`` tags."""
    if not isinstance(raw, list):
        raise ValueError("retroactive label output must be a JSON array of strings")

    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            raise ValueError("every retroactive label tag must be a string")
        tag = _normalize_tag_token(item)
        if tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
        if len(out) >= _MAX_TAGS:
            break
    if not out:
        raise ValueError("retroactive label output must contain at least one tag")
    return out


def build_forensic_taxonomy_system_prompt(
    *,
    manifest: dict[str, Any],
    context: dict[str, Any],
) -> str:
    """Backward-compatible alias for :func:`shadow_agent.main.build_evaluate_retroactive_system_prompt`."""
    from main import build_evaluate_retroactive_system_prompt  # noqa: PLC0415

    return build_evaluate_retroactive_system_prompt(manifest, context)


def build_retroactive_label_system_prompt(
    *,
    manifest_payload: dict[str, Any],
    feedback_context: dict[str, Any],
) -> str:
    """Backward-compatible alias for :func:`shadow_agent.main.build_evaluate_retroactive_system_prompt`."""
    return build_forensic_taxonomy_system_prompt(
        manifest=manifest_payload,
        context=feedback_context,
    )


async def evaluate_retroactive(
    manifest: dict[str, Any],
    context: dict[str, Any],
    *,
    llm_client: OllamaLLMClient,
) -> list[str]:
    """Delegate to :func:`shadow_agent.main.evaluate_retroactive`."""
    from main import evaluate_retroactive as _evaluate_retroactive  # noqa: PLC0415

    return await _evaluate_retroactive(
        manifest,
        context,
        llm_client=llm_client,
    )


async def evaluate_retroactive_label(
    manifest_payload: dict[str, Any],
    feedback_context: dict[str, Any],
    *,
    llm_client: OllamaLLMClient,
) -> list[str]:
    """Backward-compatible alias for :func:`evaluate_retroactive`."""
    return await evaluate_retroactive(
        manifest_payload,
        feedback_context,
        llm_client=llm_client,
    )
