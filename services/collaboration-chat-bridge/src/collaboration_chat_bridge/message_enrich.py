from __future__ import annotations

import copy
import re

from collaboration_chat_bridge.web_fetch import WebFetchError, fetch_public_text

"""Optional web URL fetch to prepend context to the last user message."""
_URL_RE = re.compile(r"https://[^\s<>\"']{8,2048}", re.IGNORECASE)


def maybe_enrich_last_user_with_web_fetch(
    messages: list[dict[str, str]],
    *,
    enabled: bool,
    max_fetch_bytes: int,
    max_prefix_chars: int,
) -> list[dict[str, str]]:
    """If enabled, detect first https URL in last user message and prepend fetched text."""
    if not enabled:
        return messages
    msgs = copy.deepcopy(messages)
    for i in range(len(msgs) - 1, -1, -1):
        if msgs[i].get("role") != "user":
            continue
        content = msgs[i].get("content") or ""
        m = _URL_RE.search(content)
        if not m:
            return msgs
        url = m.group(0).rstrip(").,;]")
        try:
            body = fetch_public_text(url, max_bytes=max_fetch_bytes)
        except WebFetchError as e:
            prefix = f"[URL fetch failed for {url}: {e}]\n\n"
            msgs[i] = {**msgs[i], "content": prefix + content}
            return msgs
        if len(body) > max_prefix_chars:
            body = body[:max_prefix_chars] + "\n…(truncated)"
        prefix = f"[Fetched reference from {url}]\n{body}\n\n---\n\n"
        msgs[i] = {**msgs[i], "content": prefix + content}
        return msgs
    return msgs
