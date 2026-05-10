"""Ollama native HTTP provider with strict structured-output validation.

Canonical home for logic that previously lived in ad-hoc ``llm_client`` helpers (none
were present in-tree at extraction time): ``httpx`` + ``/api/chat`` + ``format: json``
+ Pydantic ``model_validate`` with bounded retries.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError
from shadow_agent.providers.base import BaseLLMProvider

logger = logging.getLogger(__name__)


def _strip_json_fences(raw: str) -> str:
    """Remove optional ``` / ```json fences from model output."""
    s = raw.strip()
    if not s.startswith("```"):
        return s
    s = re.sub(r"^```(?:json)?\s*", "", s, count=1, flags=re.IGNORECASE)
    s = re.sub(r"\s*```\s*$", "", s, count=1)
    return s.strip()


def _extract_message_content(chat_response: dict[str, Any]) -> str:
    msg = chat_response.get("message")
    if not isinstance(msg, dict):
        raise KeyError("ollama response missing message object")
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return json.dumps(content, separators=(",", ":"))
    raise TypeError(f"unexpected message.content type: {type(content).__name__}")


class OllamaProvider(BaseLLMProvider):
    """
    Call Ollama ``/api/chat`` with ``format: json``, then validate against ``schema``.

    Retries only on **JSON parse** and **Pydantic validation** failures (model drift /
    formatting). HTTP transport errors propagate unless they are explicit retryable cases.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        max_json_retries: int | None = None,
        connect_timeout_sec: float = 15.0,
        read_timeout_sec: float = 120.0,
    ) -> None:
        raw_base = (base_url or os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")).strip()
        self._base_url = raw_base.rstrip("/")
        self._model = (model or os.environ.get("OLLAMA_MODEL", "llama3.2")).strip()
        self._api_key = (
            api_key if api_key is not None else os.environ.get("OLLAMA_API_KEY", "")
        ).strip()

        self._own_client = client is None
        retries_raw = (
            max_json_retries
            if max_json_retries is not None
            else os.environ.get("OLLAMA_JSON_MAX_RETRIES", "4")
        )
        self._max_json_retries = (
            int(retries_raw) if isinstance(retries_raw, str) else int(retries_raw)
        )
        if self._max_json_retries < 1:
            raise ValueError("max_json_retries must be >= 1")

        timeout = httpx.Timeout(read_timeout_sec, connect=connect_timeout_sec)
        self._client = client or httpx.AsyncClient(timeout=timeout)

    def _headers(self) -> dict[str, str]:
        if self._api_key:
            return {"Authorization": f"Bearer {self._api_key}"}
        return {}

    async def aclose(self) -> None:
        """Close the underlying HTTP client when this provider owns it."""
        if self._own_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def generate_decision(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        if not issubclass(schema, BaseModel):
            raise TypeError("schema must be a subclass of pydantic.BaseModel")

        schema_name = schema.__name__
        strict_preamble = (
            f"Respond with a single JSON object that satisfies the Pydantic model `{schema_name}` "
            "(field names and types must match). Output JSON only — no markdown, no prose."
        )
        user_block = f"{strict_preamble}\n\n{prompt}"

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": "You output machine-readable JSON only. Never wrap in code fences.",
                },
                {"role": "user", "content": user_block},
            ],
            "stream": False,
            "format": "json",
        }

        url = f"{self._base_url}/api/chat"
        last_exc: BaseException | None = None

        for attempt in range(1, self._max_json_retries + 1):
            try:
                resp = await self._client.post(url, json=payload, headers=self._headers())
                resp.raise_for_status()
                envelope = resp.json()
                raw_text = _extract_message_content(envelope)
                cleaned = _strip_json_fences(raw_text)
                parsed = json.loads(cleaned)
                if not isinstance(parsed, dict):
                    raise TypeError(
                        f"top-level JSON must be an object, got {type(parsed).__name__}"
                    )
                return schema.model_validate(parsed)
            except (json.JSONDecodeError, KeyError, TypeError, ValidationError) as exc:
                last_exc = exc
                logger.warning(
                    "ollama_structured_output_retry attempt=%s/%s schema=%s error=%s",
                    attempt,
                    self._max_json_retries,
                    schema_name,
                    exc,
                )
                continue
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < self._max_json_retries and _is_retryable_http_error(exc):
                    logger.warning(
                        "ollama_http_retry attempt=%s/%s error=%s",
                        attempt,
                        self._max_json_retries,
                        exc,
                    )
                    continue
                raise

        assert last_exc is not None
        raise RuntimeError(
            f"Ollama structured output failed after {self._max_json_retries} attempt(s) "
            f"for schema {schema_name!r}"
        ) from last_exc


def _is_retryable_http_error(exc: httpx.HTTPError) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.ConnectTimeout,
            httpx.PoolTimeout,
        ),
    )
