"""Webhook delivery with exponential backoff retry and dead letter queue.

Usage::

    sender = WebhookSender(max_retries=5)
    await sender.send("https://example.com/hook", payload={"event": "deny"})
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

log = logging.getLogger("webhook-sender")


@dataclass
class WebhookAttempt:
    url: str
    payload: dict[str, Any]
    attempt: int
    status_code: int | None
    error: str | None
    timestamp: str


@dataclass
class WebhookRecord:
    id: str
    url: str
    payload: dict[str, Any]
    status: str  # pending, delivered, failed, dlq
    attempts: list[WebhookAttempt] = field(default_factory=list)
    created_at: str = ""
    next_retry_at: float = 0


class WebhookSender:
    def __init__(
        self,
        max_retries: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 300.0,
        timeout: float = 10.0,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._timeout = timeout
        self._http = http
        self._dlq: list[WebhookRecord] = []
        self._pending: dict[str, WebhookRecord] = {}
        self._retry_task: asyncio.Task | None = None

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http:
            return self._http
        self._http = httpx.AsyncClient(timeout=self._timeout)
        return self._http

    async def send(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> WebhookRecord:
        record = WebhookRecord(
            id=uuid.uuid4().hex,
            url=url,
            payload=payload,
            status="pending",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._pending[record.id] = record
        success = await self._attempt(record, headers)
        if success:
            record.status = "delivered"
            self._pending.pop(record.id, None)
        else:
            asyncio.create_task(self._retry_loop(record, headers))
        return record

    async def _attempt(self, record: WebhookRecord, headers: dict[str, str] | None = None) -> bool:
        http = await self._get_http()
        attempt_num = len(record.attempts) + 1
        try:
            h = {"Content-Type": "application/json", "X-Webhook-Id": record.id}
            if headers:
                h.update(headers)
            r = await http.post(record.url, json=record.payload, headers=h, timeout=self._timeout)
            record.attempts.append(WebhookAttempt(
                url=record.url, payload=record.payload, attempt=attempt_num,
                status_code=r.status_code, error=None,
                timestamp=datetime.now(timezone.utc).isoformat(),
            ))
            return 200 <= r.status_code < 300
        except Exception as e:
            record.attempts.append(WebhookAttempt(
                url=record.url, payload=record.payload, attempt=attempt_num,
                status_code=None, error=str(e),
                timestamp=datetime.now(timezone.utc).isoformat(),
            ))
            return False

    async def _retry_loop(self, record: WebhookRecord, headers: dict[str, str] | None = None) -> None:
        for i in range(1, self._max_retries):
            delay = min(self._base_delay * (2 ** i), self._max_delay)
            await asyncio.sleep(delay)
            success = await self._attempt(record, headers)
            if success:
                record.status = "delivered"
                self._pending.pop(record.id, None)
                log.info("webhook delivered after %d attempts: %s", i + 1, record.url)
                return
        record.status = "dlq"
        self._pending.pop(record.id, None)
        self._dlq.append(record)
        log.warning("webhook moved to DLQ after %d attempts: %s", self._max_retries, record.url)

    def get_dlq(self) -> list[dict[str, Any]]:
        return [
            {
                "id": r.id,
                "url": r.url,
                "status": r.status,
                "attempts": len(r.attempts),
                "created_at": r.created_at,
                "last_error": r.attempts[-1].error if r.attempts else None,
            }
            for r in self._dlq
        ]

    async def retry_dlq_item(self, webhook_id: str) -> bool:
        for i, r in enumerate(self._dlq):
            if r.id == webhook_id:
                r.status = "pending"
                self._dlq.pop(i)
                success = await self._attempt(r)
                if success:
                    r.status = "delivered"
                    return True
                self._dlq.append(r)
                return False
        return False

    def get_pending(self) -> list[dict[str, Any]]:
        return [{"id": r.id, "url": r.url, "attempts": len(r.attempts)} for r in self._pending.values()]
