"""Parse model output as JSON; on ``json.loads`` failure, send the error to Ollama and retry."""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx

logger = logging.getLogger(__name__)

RepairFn = Callable[[str, str], Awaitable[str]]
"""``(broken_text, error_message) -> replacement_text`` — async hook or Ollama round-trip."""


def strip_json_fences(raw: str) -> str:
    """Remove optional Markdown `` ``` `` / `` ```json `` fences from model output."""
    s = raw.strip()
    if not s.startswith("```"):
        return s
    s = re.sub(r"^```(?:json)?\s*", "", s, count=1, flags=re.IGNORECASE)
    s = re.sub(r"\s*```\s*$", "", s, count=1)
    return s.strip()


def loads_json_loose(text: str) -> Any:
    """``json.loads`` after fence stripping (single attempt, no repair)."""
    return json.loads(strip_json_fences(text))


def ollama_fix_messages(*, broken_text: str, error_message: str) -> list[dict[str, str]]:
    """Build ``/api/chat`` messages that include the decode error and the broken snippet."""
    snippet = broken_text.strip()
    if len(snippet) > 24_000:
        snippet = snippet[:24_000] + "\n…(truncated)"
    return [
        {
            "role": "system",
            "content": (
                "You are a strict JSON repair assistant. The user will show a JSON parse error and a broken "
                "fragment. Reply with a single valid JSON value only (object or array as appropriate). "
                "No markdown fences, no commentary."
            ),
        },
        {
            "role": "user",
            "content": (
                f"The following text failed JSON parsing.\n\n"
                f"Parse error:\n{error_message}\n\n"
                f"Broken text:\n{snippet}\n\n"
                f"Return corrected JSON only."
            ),
        },
    ]


def _assistant_content(payload: Mapping[str, Any]) -> str:
    msg = payload.get("message")
    if not isinstance(msg, dict):
        raise ValueError("Ollama response missing dict 'message'")
    content = msg.get("content")
    if not isinstance(content, str):
        raise ValueError("Ollama message.content must be a string")
    return content


async def loads_json_with_repair(
    text: str,
    *,
    repair: RepairFn,
    max_repairs: int = 2,
) -> Any:
    """
    Try ``json.loads`` (with fence strip). On each failure, call ``repair(broken_text, str(exc))`` and retry.

    ``max_repairs`` is the number of **repair** rounds after the initial failed parse (default **2**).
    With ``max_repairs=1``, there are at most two parse attempts: initial text, then one repaired string.
    """
    if max_repairs < 0:
        raise ValueError("max_repairs must be >= 0")

    current = text
    for repair_round in range(max_repairs + 1):
        try:
            return loads_json_loose(current)
        except json.JSONDecodeError as exc:
            if repair_round >= max_repairs:
                logger.warning(
                    "json_repair_exhausted rounds=%s colno=%s pos=%s",
                    repair_round,
                    exc.colno,
                    exc.pos,
                )
                raise
            err_msg = str(exc)
            logger.info(
                "json_repair_invoking round=%s/%s colno=%s",
                repair_round + 1,
                max_repairs,
                exc.colno,
            )
            current = await repair(current, err_msg)
    raise RuntimeError("json repair loop fell through")  # pragma: no cover


async def loads_json_with_ollama_repair(
    text: str,
    *,
    client: httpx.AsyncClient,
    model: str | None = None,
    max_repairs: int = 2,
) -> Any:
    """
    Same as :func:`loads_json_with_repair`, using Ollama ``POST /api/chat`` with ``format: json``.

    ``client`` must target the Ollama base URL (e.g. ``httpx.AsyncClient(base_url='http://localhost:11434')``).
    ``model`` defaults to ``OLLAMA_MODEL`` or ``llama3.2``.
    """
    use_model = (model or os.environ.get("OLLAMA_MODEL") or "llama3.2").strip()

    async def _ollama_repair(broken: str, err: str) -> str:
        body: dict[str, Any] = {
            "model": use_model,
            "messages": ollama_fix_messages(broken_text=broken, error_message=err),
            "stream": False,
            "format": "json",
        }
        r = await client.post("/api/chat", json=body)
        r.raise_for_status()
        return _assistant_content(r.json())

    return await loads_json_with_repair(text, repair=_ollama_repair, max_repairs=max_repairs)
