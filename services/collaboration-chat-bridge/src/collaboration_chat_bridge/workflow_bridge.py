"""Strip !wf / !wfp / !style from last user message; map to investigation-agent workflow_id + workflow_params."""

from __future__ import annotations

import copy
import re

# Aligns with common workflow manifests (e.g. sop_case_summary_v1: audience, report_label).
_STYLE_TO_PARAMS: dict[str, dict[str, str]] = {
    "standard": {},
    "concise": {"report_label": "Concise"},
    "detailed": {"report_label": "Detailed"},
    "executive": {"audience": "executive"},
    "tutorial": {"report_label": "Tutorial"},
}

_WF_LINE = re.compile(r"^!wf\s+([a-zA-Z0-9_.-]{1,80})\s*$", re.IGNORECASE)
_WFP_LINE = re.compile(r"^!wfp\s+(.+)$", re.IGNORECASE)
_STYLE_LINE = re.compile(
    r"^!style\s+(standard|concise|detailed|executive|tutorial)\s*$",
    re.IGNORECASE,
)


def _parse_wfp_payload(rest: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in rest.split():
        if "=" not in part:
            continue
        k, _, v = part.partition("=")
        k = k.strip()
        v = v.strip()
        if k and v and len(k) <= 64 and len(v) <= 512:
            out[k] = v
    return out


def strip_workflow_directives_from_text(text: str) -> tuple[str, str | None, dict[str, str]]:
    """
    Remove lines that are only !wf / !wfp / !style directives; return workflow_id, merged params, cleaned text.
    """
    lines = text.splitlines()
    kept: list[str] = []
    workflow_id: str | None = None
    params: dict[str, str] = {}
    for line in lines:
        s = line.strip()
        m_wf = _WF_LINE.match(s)
        if m_wf:
            workflow_id = m_wf.group(1).strip()
            continue
        m_wfp = _WFP_LINE.match(s)
        if m_wfp:
            params.update(_parse_wfp_payload(m_wfp.group(1)))
            continue
        m_st = _STYLE_LINE.match(s)
        if m_st:
            style = m_st.group(1).lower()
            params.update(_STYLE_TO_PARAMS.get(style, {}))
            continue
        kept.append(line)
    cleaned = "\n".join(kept).strip()
    return cleaned, workflow_id, params


def resolve_workflow_from_messages(
    messages: list[dict[str, str]],
) -> tuple[list[dict[str, str]], str | None, dict[str, str]]:
    """Apply directive stripping to the last user message only; deep-copy messages."""
    msgs = copy.deepcopy(messages)
    for i in range(len(msgs) - 1, -1, -1):
        if msgs[i].get("role") != "user":
            continue
        content = msgs[i].get("content") or ""
        cleaned, wf_id, params = strip_workflow_directives_from_text(content)
        msgs[i] = {**msgs[i], "content": cleaned}
        return msgs, wf_id, params
    return msgs, None, {}
