from __future__ import annotations

"""Resolve copilot persona for bridge → investigation-agent: env default, optional API body, or message prefix."""


import copy as _copy
import re
from typing import Literal

CopilotPersonaId = Literal["investigation", "orchestrator"]


def strip_persona_command(text: str) -> tuple[str, CopilotPersonaId | None]:
    """Strip leading `!orch` / `!orchestrator` / `!inv` / `!investigation` (optional body after whitespace)."""
    s = text.lstrip()
    if not s:
        return text, None
    m = re.match(
        r"^!(?P<cmd>orch|orchestrator|inv|investigation)(?:\s+(?P<rest>.*))?$",
        s,
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return text, None
    cmd = m.group("cmd").lower()
    rest = (m.group("rest") or "").strip()
    if cmd in ("orch", "orchestrator"):
        return rest, "orchestrator"
    return rest, "investigation"


def _normalize_default(raw: str) -> CopilotPersonaId:
    v = (raw or "investigation").strip().lower()
    return v if v in ("investigation", "orchestrator") else "investigation"


def resolve_copilot_persona_for_bridge(
    default: str,
    messages: list[dict[str, str]],
    explicit: str | None = None,
) -> tuple[CopilotPersonaId, list[dict[str, str]]]:
    """
    Precedence: explicit API persona (Teams) > `!orch` / `!inv` on last user message > default from settings.
    """
    if explicit is not None and str(explicit).strip():
        e = str(explicit).strip().lower()
        if e in ("investigation", "orchestrator"):
            return e, _copy.deepcopy(messages)

    base = _normalize_default(default)
    msgs = _copy.deepcopy(messages)
    for i in range(len(msgs) - 1, -1, -1):
        if msgs[i].get("role") != "user":
            continue
        content = msgs[i].get("content") or ""
        cleaned, p = strip_persona_command(content)
        if p is not None:
            msgs[i] = {**msgs[i], "content": cleaned}
            return p, msgs
        break
    return base, msgs
