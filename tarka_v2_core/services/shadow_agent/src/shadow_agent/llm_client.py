"""Async HTTP client for a local Ollama server with pooling, retries, and timeouts.

Uses ``httpx.AsyncClient`` (keep-alive pool) and ``tenacity.asyncio.AsyncRetrying`` for
bounded exponential backoff with jitter on transient transport errors and retryable HTTP
status codes (429, 502, 503, 504).

Strict JSON validation (``chat_json_validated``) parses assistant ``message.content``
with ``json.loads`` after optional fence stripping; on failure a bounded self-correction
loop re-prompts the model (default: two retries).
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeVar

import httpx
from tenacity import RetryCallState, retry_if_exception, stop_after_attempt, wait_exponential_jitter
from tenacity.asyncio import AsyncRetrying

from shadow_agent.ai_gateway.base import AIGateway
from shadow_agent.ai_gateway.factory import build_ai_gateway

logger = logging.getLogger(__name__)

T = TypeVar("T")

_RETRYABLE_HTTP = frozenset({429, 502, 503, 504})

_JSON_FIX_USER_PROMPT = "This is invalid JSON, fix it."
_DEFAULT_JSON_SELF_CORRECTION_RETRIES = 2


class ShadowLLMError(RuntimeError):
    """Raised when strict JSON validation fails after exhausting self-correction attempts."""

    def __init__(
        self,
        message: str,
        *,
        reason: str,
        raw_content: str | None = None,
        parse_attempts: int = 0,
        last_chat_response: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.raw_content = raw_content
        self.parse_attempts = parse_attempts
        self.last_chat_response = last_chat_response


def _strip_json_fences(raw: str) -> str:
    """Remove optional Markdown ``` / ```json fences from model output."""
    s = raw.strip()
    if not s.startswith("```"):
        return s
    s = re.sub(r"^```(?:json)?\s*", "", s, count=1, flags=re.IGNORECASE)
    s = re.sub(r"\s*```\s*$", "", s, count=1)
    return s.strip()


def _assistant_text_from_chat_response(payload: dict[str, Any]) -> str:
    """Return assistant ``message.content`` as a string suitable for ``json.loads``."""
    msg = payload.get("message")
    if not isinstance(msg, dict):
        raise ShadowLLMError(
            "Ollama chat response is missing a dict-shaped 'message' field.",
            reason="invalid_assistant_envelope",
            parse_attempts=0,
            last_chat_response=payload,
        )
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return json.dumps(content, separators=(",", ":"))
    raise ShadowLLMError(
        f"Ollama message.content has unsupported type {type(content).__name__}.",
        reason="invalid_assistant_envelope",
        parse_attempts=0,
        last_chat_response=payload,
    )


def _parse_json_from_assistant_text(text: str) -> Any:
    """Parse assistant text as JSON after fence stripping."""
    stripped = _strip_json_fences(text)
    return json.loads(stripped)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_HTTP
    return isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.PoolTimeout,
            httpx.RemoteProtocolError,
            httpx.ReadError,
            httpx.WriteError,
        ),
    )


def _log_before_retry(retry_state: RetryCallState, operation: str) -> None:
    outcome = retry_state.outcome
    exc = outcome.exception() if outcome is not None and outcome.failed else None
    sleep_s: float | None = None
    if retry_state.next_action is not None and hasattr(retry_state.next_action, "sleep"):
        sleep_s = float(retry_state.next_action.sleep)
    logger.warning(
        "ollama_http_retry operation=%s attempt=%s sleep_s=%s error=%r",
        operation,
        retry_state.attempt_number,
        sleep_s,
        exc,
    )


class OllamaLLMClient:
    """Pooled async client for Ollama ``/api/chat`` and lightweight ``/api/tags`` probes."""

    DEFAULT_BASE_URL = "http://localhost:11434"
    DEFAULT_MODEL = "llama3.2"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        connect_timeout_sec: float = 15.0,
        read_timeout_sec: float = 300.0,
        write_timeout_sec: float = 60.0,
        pool_timeout_sec: float = 10.0,
        max_retries: int = 5,
        retry_wait_initial_sec: float = 0.5,
        retry_wait_max_sec: float = 30.0,
        limits: httpx.Limits | None = None,
        client: httpx.AsyncClient | None = None,
        ai_gateway: AIGateway | None = None,
    ) -> None:
        self._ai_gateway = ai_gateway if ai_gateway is not None else build_ai_gateway()

        if client is not None:
            self._base_url = str(client.base_url).rstrip("/")
        elif base_url is not None:
            self._base_url = base_url.strip().rstrip("/")
        else:
            self._base_url = (
                (os.environ.get("OLLAMA_HOST") or "").strip()
                or self._ai_gateway.shadow_investigate_base_url.strip()
                or self.DEFAULT_BASE_URL
            ).rstrip("/")
        self._default_model = (model or os.environ.get("OLLAMA_MODEL", self.DEFAULT_MODEL)).strip()
        self._api_key = (
            api_key if api_key is not None else os.environ.get("OLLAMA_API_KEY", "")
        ).strip()

        if max_retries < 1:
            raise ValueError("max_retries must be >= 1")
        self._max_retries = max_retries
        self._retry_wait_initial = retry_wait_initial_sec
        self._retry_wait_max = retry_wait_max_sec

        self._own_client = client is None
        if client is not None and not client.base_url.host:
            raise ValueError(
                "injected httpx.AsyncClient must set base_url to the Ollama origin "
                f"(e.g. {self._base_url!r})",
            )

        pool_limits = limits or httpx.Limits(max_keepalive_connections=20, max_connections=100)
        self._default_timeout = httpx.Timeout(
            connect=connect_timeout_sec,
            read=read_timeout_sec,
            write=write_timeout_sec,
            pool=pool_timeout_sec,
        )
        self._ping_timeout = httpx.Timeout(
            connect=min(10.0, connect_timeout_sec),
            read=15.0,
            write=min(10.0, write_timeout_sec),
            pool=min(10.0, pool_timeout_sec),
        )

        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            limits=pool_limits,
            timeout=self._default_timeout,
        )

    def _headers(self) -> dict[str, str]:
        if self._api_key:
            return {"Authorization": f"Bearer {self._api_key}"}
        return {}

    async def __aenter__(self) -> OllamaLLMClient:
        return self

    async def __aexit__(self, _exc_type: object, _exc: BaseException | None, _tb: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying HTTP client when this instance owns it."""
        if self._own_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _execute_with_retries(
        self, operation: str, coro_factory: Callable[[], Awaitable[T]]
    ) -> T:
        def _before_sleep(retry_state: RetryCallState) -> None:
            _log_before_retry(retry_state, operation)

        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential_jitter(
                initial=self._retry_wait_initial,
                max=self._retry_wait_max,
            ),
            retry=retry_if_exception(_is_retryable),
            reraise=True,
            before_sleep=_before_sleep,
        )
        async for attempt in retrying:
            with attempt:
                return await coro_factory()

    async def ping(self) -> httpx.Response:
        """GET ``/api/tags`` (single attempt, uses a short timeout). No retry wrapper."""

        if self._client is None:
            raise RuntimeError("OllamaLLMClient is closed")
        return await self._client.get(
            "/api/tags",
            headers=self._headers(),
            timeout=self._ping_timeout,
        )

    async def chat(
        self,
        messages: list[Mapping[str, Any]],
        *,
        model: str | None = None,
        format_json: bool = True,
        stream: bool = False,
    ) -> dict[str, Any]:
        """POST ``/api/chat`` with optional ``format: json``; returns the Ollama JSON object."""

        if self._client is None:
            raise RuntimeError("OllamaLLMClient is closed")

        use_model = (model or self._default_model).strip()
        body: dict[str, Any] = {
            "model": use_model,
            "messages": [dict(m) for m in messages],
            "stream": stream,
        }
        if format_json:
            body["format"] = "json"

        async def _post_chat() -> dict[str, Any]:
            response = await self._client.post(
                "/api/chat",
                json=body,
                headers=self._headers(),
            )
            response.raise_for_status()
            return response.json()

        async def _chat_pipeline() -> dict[str, Any]:
            return await self._execute_with_retries("chat", _post_chat)

        return await self._ai_gateway.run_shadow_investigate_inference(_chat_pipeline)

    async def chat_json_validated(
        self,
        messages: list[Mapping[str, Any]],
        *,
        model: str | None = None,
        json_self_correction_retries: int = _DEFAULT_JSON_SELF_CORRECTION_RETRIES,
    ) -> Any:
        """Call ``/api/chat`` with ``format: json``, then ``json.loads`` on assistant content.

        If parsing fails, re-sends the invalid assistant output with the user message
        "This is invalid JSON, fix it." (up to ``json_self_correction_retries`` times).

        Raises:
            ShadowLLMError: If the envelope is invalid or JSON never parses after retries.
        """
        if json_self_correction_retries < 0:
            raise ValueError("json_self_correction_retries must be >= 0")

        base_messages = [dict(m) for m in messages]
        current_messages: list[dict[str, Any]] = list(base_messages)
        last_raw: dict[str, Any] | None = None
        last_text: str | None = None
        max_parse_attempts = json_self_correction_retries + 1

        for parse_attempt in range(max_parse_attempts):
            last_raw = await self.chat(
                current_messages,
                model=model,
                format_json=True,
                stream=False,
            )
            last_text = _assistant_text_from_chat_response(last_raw)
            try:
                return _parse_json_from_assistant_text(last_text)
            except json.JSONDecodeError as exc:
                preview = last_text[:200].replace("\n", "\\n") if last_text else ""
                logger.warning(
                    "ollama_json_parse_failed attempt=%s/%s colno=%s pos=%s preview=%r",
                    parse_attempt + 1,
                    max_parse_attempts,
                    exc.colno,
                    exc.pos,
                    preview,
                )
                if parse_attempt >= json_self_correction_retries:
                    raise ShadowLLMError(
                        "Assistant output was not valid JSON after "
                        f"{json_self_correction_retries} self-correction retries.",
                        reason="json_decode_exhausted",
                        raw_content=last_text,
                        parse_attempts=parse_attempt + 1,
                        last_chat_response=last_raw,
                    ) from exc
                current_messages = [
                    *base_messages,
                    {"role": "assistant", "content": last_text},
                    {"role": "user", "content": _JSON_FIX_USER_PROMPT},
                ]


__all__ = ["OllamaLLMClient", "ShadowLLMError"]
