from __future__ import annotations

import logging
from typing import Any

from collaboration_chat_bridge.attachments import slack_files_to_append_text
from collaboration_chat_bridge.config import Settings
from collaboration_chat_bridge.message_enrich import maybe_enrich_last_user_with_web_fetch
from collaboration_chat_bridge.persona_bridge import resolve_copilot_persona_for_bridge
from collaboration_chat_bridge.workflow_bridge import resolve_workflow_from_messages

"""Shared pipeline: workflow directives → Slack files → web fetch → persona → agent payload."""
log = logging.getLogger(__name__)


def append_to_last_user_content(
    messages: list[dict[str, str]], appendix: str
) -> list[dict[str, str]]:
    if not appendix.strip():
        return messages
    import copy

    msgs = copy.deepcopy(messages)
    for i in range(len(msgs) - 1, -1, -1):
        if msgs[i].get("role") != "user":
            continue
        c = msgs[i].get("content") or ""
        msgs[i] = {**msgs[i], "content": (c + appendix).strip()}
        break
    return msgs


async def prepare_messages_for_agent(
    settings: Settings,
    messages: list[dict[str, str]],
    *,
    slack_files: list[dict[str, Any]] | None,
    slack_bot_token: str,
    explicit_persona: str | None = None,
) -> tuple[list[dict[str, str]], str | None, dict[str, str], str]:
    """
    Returns (messages, workflow_id, workflow_params, persona).
    Order: workflow strip → Slack file append → web fetch → persona resolution.
    """
    msgs, wf_id, wf_params = resolve_workflow_from_messages(messages)

    if slack_files and (settings.slack_bot_token or "").strip():
        try:
            extra = await slack_files_to_append_text(
                slack_files,
                slack_bot_token,
                max_bytes_per_file=settings.bridge_attachment_max_bytes,
                max_total_chars=settings.bridge_attachment_max_total_chars,
            )
            if extra:
                msgs = append_to_last_user_content(msgs, extra)
        except Exception as e:  # noqa: BLE001
            log.warning("slack attachment handling failed: %s", e)

    msgs = maybe_enrich_last_user_with_web_fetch(
        msgs,
        enabled=settings.bridge_web_fetch_enabled,
        max_fetch_bytes=settings.bridge_web_fetch_max_bytes,
        max_prefix_chars=settings.bridge_web_fetch_max_prefix_chars,
    )

    persona, msgs = resolve_copilot_persona_for_bridge(
        settings.default_copilot_persona,
        msgs,
        explicit=explicit_persona,
    )
    return msgs, wf_id, wf_params, persona


def merge_workflow_with_explicit(
    msg_wf_id: str | None,
    msg_params: dict[str, str],
    *,
    explicit_workflow_id: str | None,
    explicit_params: dict[str, Any] | None,
) -> tuple[str | None, dict[str, str]]:
    """Teams/Lark JSON overrides message-derived workflow id; params merge (explicit wins)."""
    wid = (explicit_workflow_id or "").strip() or msg_wf_id
    merged: dict[str, str] = dict(msg_params)
    if isinstance(explicit_params, dict) and explicit_params:
        for k, v in explicit_params.items():
            if k and str(v).strip():
                merged[str(k)[:64]] = str(v)[:512]
    return wid, merged
