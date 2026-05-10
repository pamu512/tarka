"""OpenAI Chat Completions provider with Structured Outputs or JSON-object mode."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from openai import APIStatusError, AsyncOpenAI
from pydantic import BaseModel, ValidationError
from shadow_agent.providers.base import BaseLLMProvider

logger = logging.getLogger(__name__)

# Models known to support ``response_format.type == "json_schema"`` (Structured Outputs).
_JSON_SCHEMA_PREFIXES: tuple[str, ...] = (
    "gpt-4o",
    "gpt-4.1",
    "o1",
    "o3",
    "o4",
    "chatgpt-4o",
)


def _strip_json_fences(raw: str) -> str:
    s = raw.strip()
    if not s.startswith("```"):
        return s
    s = re.sub(r"^```(?:json)?\s*", "", s, count=1, flags=re.IGNORECASE)
    s = re.sub(r"\s*```\s*$", "", s, count=1)
    return s.strip()


def model_supports_json_schema(model: str) -> bool:
    """Heuristic: whether to request OpenAI Structured Outputs (``json_schema``)."""
    m = model.strip().lower()
    return any(m.startswith(p) for p in _JSON_SCHEMA_PREFIXES)


class OpenAIProvider(BaseLLMProvider):
    """
    ``AsyncOpenAI`` chat completions with schema-bound results.

    - If the configured model appears to support Structured Outputs, uses
      ``response_format={"type": "json_schema", ...}`` with ``strict: True``.
    - Otherwise uses ``response_format={"type": "json_object"}`` and enforces shape
      via prompt text plus Pydantic ``model_validate`` (with bounded retries on drift).

    API key: ``OPENAI_API_KEY`` (required unless an ``AsyncOpenAI`` client is injected).
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        client: AsyncOpenAI | None = None,
        max_json_retries: int | None = None,
        organization: str | None = None,
    ) -> None:
        self._model = (model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")).strip()
        key = (api_key if api_key is not None else os.environ.get("OPENAI_API_KEY", "")).strip()
        self._own_client = client is None
        if self._own_client and not key:
            raise ValueError(
                "OPENAI_API_KEY is required when no AsyncOpenAI client is injected",
            )

        retries_raw = (
            max_json_retries
            if max_json_retries is not None
            else os.environ.get("OPENAI_JSON_MAX_RETRIES", "4")
        )
        self._max_json_retries = (
            int(retries_raw) if isinstance(retries_raw, str) else int(retries_raw)
        )
        if self._max_json_retries < 1:
            raise ValueError("max_json_retries must be >= 1")

        org = (
            organization.strip()
            if organization is not None
            else os.environ.get("OPENAI_ORG_ID", "").strip() or None
        )
        bu = (base_url or os.environ.get("OPENAI_BASE_URL", "").strip() or None) or None

        self._client = client or AsyncOpenAI(api_key=key, base_url=bu, organization=org)

    async def aclose(self) -> None:
        if self._own_client and self._client is not None:
            await self._client.close()
            self._client = None  # type: ignore[assignment]

    def _structured_response_format(self, schema: type[BaseModel]) -> dict[str, Any]:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__,
                "schema": schema.model_json_schema(),
                "strict": True,
            },
        }

    def _messages(
        self, prompt: str, schema: type[BaseModel], *, json_object_mode: bool
    ) -> list[dict[str, str]]:
        if json_object_mode:
            schema_hint = json.dumps(schema.model_json_schema(), separators=(",", ":"))
            if len(schema_hint) > 14_000:
                schema_hint = schema_hint[:14_000] + "…"
            system = (
                "You reply with a single JSON object only (no markdown, no prose). "
                "The object must be parseable against this JSON Schema (field names and types must match):\n"
                f"{schema_hint}"
            )
        else:
            system = (
                "You reply with a single JSON object only (no markdown, no prose). "
                "The object must satisfy the caller's json_schema Structured Output contract."
            )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]

    async def _create_completion(
        self,
        *,
        messages: list[dict[str, str]],
        response_format: dict[str, Any],
    ) -> Any:
        return await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=0,
            response_format=response_format,  # type: ignore[arg-type]
        )

    async def generate_decision(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        if not issubclass(schema, BaseModel):
            raise TypeError("schema must be a subclass of pydantic.BaseModel")

        prefer_structured = model_supports_json_schema(self._model)
        if os.environ.get("OPENAI_FORCE_JSON_OBJECT", "").lower() in ("1", "true", "yes"):
            prefer_structured = False

        use_structured = prefer_structured
        schema_name = schema.__name__
        last_exc: BaseException | None = None
        fell_back_from_schema = False

        for attempt in range(1, self._max_json_retries + 1):
            messages = self._messages(prompt, schema, json_object_mode=not use_structured)
            rf: dict[str, Any]
            if use_structured:
                rf = self._structured_response_format(schema)
            else:
                rf = {"type": "json_object"}

            try:
                completion = await self._create_completion(messages=messages, response_format=rf)
            except APIStatusError as exc:
                last_exc = exc
                if use_structured and exc.status_code == 400 and not fell_back_from_schema:
                    body_excerpt = ""
                    try:
                        if exc.response is not None and exc.response.text:
                            body_excerpt = exc.response.text[:800]
                    except Exception:
                        body_excerpt = ""
                    logger.warning(
                        "openai_json_schema_rejected_falling_back_to_json_object status=%s excerpt=%s err=%s",
                        exc.status_code,
                        body_excerpt,
                        exc,
                    )
                    use_structured = False
                    fell_back_from_schema = True
                    continue
                if attempt < self._max_json_retries and exc.status_code in (
                    429,
                    500,
                    502,
                    503,
                    504,
                ):
                    logger.warning(
                        "openai_chat_completion_retryable_http attempt=%s/%s err=%s",
                        attempt,
                        self._max_json_retries,
                        exc,
                    )
                    continue
                raise

            msg = completion.choices[0].message
            refusal = getattr(msg, "refusal", None)
            if refusal:
                last_exc = RuntimeError(f"model refusal: {refusal}")
                logger.warning(
                    "openai_model_refusal attempt=%s/%s refusal=%s",
                    attempt,
                    self._max_json_retries,
                    refusal,
                )
                continue

            raw = msg.content
            if raw is None or not str(raw).strip():
                last_exc = ValueError("empty message content from OpenAI")
                logger.warning(
                    "openai_empty_content attempt=%s/%s",
                    attempt,
                    self._max_json_retries,
                )
                continue

            try:
                cleaned = _strip_json_fences(str(raw))
                parsed = json.loads(cleaned)
                if not isinstance(parsed, dict):
                    raise TypeError(
                        f"top-level JSON must be an object, got {type(parsed).__name__}"
                    )
                return schema.model_validate(parsed)
            except (json.JSONDecodeError, TypeError, ValidationError) as exc:
                last_exc = exc
                logger.warning(
                    "openai_structured_output_retry attempt=%s/%s schema=%s err=%s",
                    attempt,
                    self._max_json_retries,
                    schema_name,
                    exc,
                )
                continue

        assert last_exc is not None
        raise RuntimeError(
            f"OpenAI structured output failed after {self._max_json_retries} attempt(s) "
            f"for schema {schema_name!r}"
        ) from last_exc
