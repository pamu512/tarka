from __future__ import annotations

import re
from typing import Any


def _trim(s: str, max_len: int = 3500) -> str:
    s = (s or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 20] + "\n…(truncated)"


def escape_slack_mrkdwn(text: str) -> str:
    """Escape &, <, > so model/user content does not break Block Kit mrkdwn."""
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _section_blocks(
    sections: dict[str, Any],
    *,
    include_secondary: bool,
) -> list[dict[str, Any]]:
    """Optional FACTS_FROM_TOOLS and UNKNOWNS (structured copilot sections)."""
    blocks: list[dict[str, Any]] = []
    if not include_secondary:
        return blocks
    facts = sections.get("facts_from_tools")
    if facts:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*FACTS FROM TOOLS*\n{escape_slack_mrkdwn(_trim(str(facts), 1200))}",
                },
            }
        )
    unk = sections.get("unknowns")
    if unk:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*UNKNOWNS*\n{escape_slack_mrkdwn(_trim(str(unk), 1200))}",
                },
            }
        )
    return blocks


def format_slack_blocks(
    agent_json: dict[str, Any],
    *,
    include_secondary_sections: bool = True,
) -> list[dict[str, Any]]:
    """Build Slack Block Kit from investigation-agent /v1/chat response."""
    reply = escape_slack_mrkdwn(_trim(str(agent_json.get("reply") or ""), 2900))
    sections = agent_json.get("answer_sections") if isinstance(agent_json.get("answer_sections"), dict) else {}
    blocks: list[dict[str, Any]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Copilot*\n{reply or '_No reply_'}"}},
    ]
    blocks.extend(_section_blocks(sections, include_secondary=include_secondary_sections))

    inf = sections.get("inferences") if isinstance(sections, dict) else None
    ns = sections.get("next_steps") if isinstance(sections, dict) else None
    if inf:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*INFERENCES*\n{escape_slack_mrkdwn(_trim(str(inf), 1500))}"},
            }
        )
    if ns:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*NEXT STEPS*\n{escape_slack_mrkdwn(_trim(str(ns), 1500))}"},
            }
        )
    turn_id = agent_json.get("turn_id")
    persona = agent_json.get("persona")
    ctx_bits: list[str] = []
    if persona:
        ctx_bits.append(f"`persona`: `{persona}`")
    if turn_id:
        ctx_bits.append(f"`turn_id`: `{turn_id}`")
    if ctx_bits:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": " · ".join(ctx_bits)}]})
    return blocks


def format_slack_error_blocks(message: str, *, detail: str = "") -> list[dict[str, Any]]:
    """User-visible Slack message when the copilot call fails."""
    body = escape_slack_mrkdwn(_trim(message, 500))
    extra = f"\n_{escape_slack_mrkdwn(_trim(detail, 400))}_" if detail else ""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":warning: *Copilot unavailable*\n{body}{extra}",
            },
        }
    ]


def format_teams_adaptive_card(
    agent_json: dict[str, Any],
    *,
    include_secondary_sections: bool = True,
) -> dict[str, Any]:
    """Adaptive Card for Teams (connector / Bot HTTP post)."""
    reply = _trim(str(agent_json.get("reply") or ""), 4000)
    sections = agent_json.get("answer_sections") if isinstance(agent_json.get("answer_sections"), dict) else {}
    body: list[dict[str, Any]] = [
        {"type": "TextBlock", "text": "Copilot", "weight": "Bolder", "size": "Medium"},
        {"type": "TextBlock", "text": reply or "—", "wrap": True},
    ]
    if include_secondary_sections:
        facts = sections.get("facts_from_tools")
        if facts:
            body.append({"type": "TextBlock", "text": "FACTS FROM TOOLS", "weight": "Bolder", "spacing": "Medium"})
            body.append({"type": "TextBlock", "text": _trim(str(facts), 1800), "wrap": True, "isSubtle": True})
        unk = sections.get("unknowns")
        if unk:
            body.append({"type": "TextBlock", "text": "UNKNOWNS", "weight": "Bolder", "spacing": "Medium"})
            body.append({"type": "TextBlock", "text": _trim(str(unk), 1800), "wrap": True, "isSubtle": True})
    inf = sections.get("inferences") if isinstance(sections, dict) else None
    ns = sections.get("next_steps") if isinstance(sections, dict) else None
    if inf:
        body.append({"type": "TextBlock", "text": "INFERENCES", "weight": "Bolder", "spacing": "Medium"})
        body.append({"type": "TextBlock", "text": _trim(str(inf), 2000), "wrap": True})
    if ns:
        body.append({"type": "TextBlock", "text": "NEXT STEPS", "weight": "Bolder", "spacing": "Medium"})
        body.append({"type": "TextBlock", "text": _trim(str(ns), 2000), "wrap": True})
    turn_id = agent_json.get("turn_id")
    persona = agent_json.get("persona")
    facts: list[dict[str, str]] = []
    if persona:
        facts.append({"title": "persona", "value": str(persona)})
    if turn_id:
        facts.append({"title": "turn_id", "value": str(turn_id)})
    if facts:
        body.append({"type": "FactSet", "facts": facts, "spacing": "Medium"})
    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": body,
    }


def format_teams_error_card(title: str, detail: str = "") -> dict[str, Any]:
    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": title,
                "weight": "Bolder",
                "color": "Attention",
                "wrap": True,
            },
            {"type": "TextBlock", "text": _trim(detail, 1500) or "—", "wrap": True, "isSubtle": True},
        ],
    }


def format_lark_card_text(agent_json: dict[str, Any]) -> str:
    """Plain text for Lark post message API."""
    reply = _trim(str(agent_json.get("reply") or ""), 3000)
    sections = agent_json.get("answer_sections") if isinstance(agent_json.get("answer_sections"), dict) else {}
    parts = ["**Copilot**", reply]
    facts = sections.get("facts_from_tools")
    unk = sections.get("unknowns")
    if facts:
        parts.extend(["", "**FACTS FROM TOOLS**", _trim(str(facts), 1200)])
    if unk:
        parts.extend(["", "**UNKNOWNS**", _trim(str(unk), 1200)])
    inf = sections.get("inferences") if isinstance(sections, dict) else None
    ns = sections.get("next_steps") if isinstance(sections, dict) else None
    if inf:
        parts.extend(["", "**INFERENCES**", _trim(str(inf), 1500)])
    if ns:
        parts.extend(["", "**NEXT STEPS**", _trim(str(ns), 1500)])
    per = agent_json.get("persona")
    if per:
        parts.append(f"\n`persona`: {per}")
    tid = agent_json.get("turn_id")
    if tid:
        parts.append(f"\n`turn_id`: {tid}")
    return "\n".join(parts)


def format_lark_error_text(message: str, detail: str = "") -> str:
    """User-visible Lark error copy — never include upstream stack traces or raw HTTP bodies."""
    safe_msg = _trim(message, 800) if message else "Copilot is temporarily unavailable."
    return "**Copilot error**\n" + safe_msg


# Strip Slack mention tokens and link noise for cleaner user prompts.
# Use bounded quantifiers (not unbounded +) to avoid polynomial ReDoS on hostile input (CodeQL py/polynomial-redos).
_SLACK_USER_MENTION = re.compile(r"<@[^>\s]{1,256}>\s*")
_SLACK_SUBTEAM = re.compile(r"<!subteam\^[^>\s]{1,256}>\s*")
_SLACK_LINK = re.compile(r"<(https?://[^|>]{1,2048})\|[^>]{1,512}>")
_SLACK_BARE_URL = re.compile(r"<(https?://[^>\s]{1,2048})>")
_MAX_SLACK_NORMALIZE_CHARS = 100_000


def normalize_slack_user_text(text: str) -> str:
    """Remove @bot mentions and normalize Slack <url|label> / <url> tokens for LLM context."""
    t = (text or "").strip()
    if len(t) > _MAX_SLACK_NORMALIZE_CHARS:
        t = t[:_MAX_SLACK_NORMALIZE_CHARS]
    t = _SLACK_USER_MENTION.sub("", t)
    t = _SLACK_SUBTEAM.sub("", t)
    t = _SLACK_LINK.sub(r"\1", t)
    t = _SLACK_BARE_URL.sub(r"\1", t)
    return t.strip()
