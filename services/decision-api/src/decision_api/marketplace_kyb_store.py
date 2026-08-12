"""Durable marketplace KYB seller records (Redis + file + memory fallback)."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

import redis.asyncio as aioredis

log = logging.getLogger("decision-api.marketplace_kyb_store")

KYB_PREFIX = "fraud:mkt_kyb:"
KYB_TTL_SECONDS = 86400 * 365  # 1 year — seller integrity memory


def _file_path_from_env() -> Path | None:
    raw = (
        os.environ.get("TARKA_KYB_STORE_PATH")
        or os.environ.get("KYB_STORE_PATH")
        or ""
    ).strip()
    if not raw:
        return None
    return Path(raw)


class MarketplaceKybStore:
    """Redis-backed KYB records; optional JSON file for CI; memory last resort.

    ponytail: memory/file ceiling = multi-replica inconsistency; Redis is the HA path.
    """

    def __init__(self, file_path: Path | None = None) -> None:
        self._client: aioredis.Redis | None = None
        self._memory: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._file_path = file_path if file_path is not None else _file_path_from_env()
        if self._file_path is not None:
            self._load_file_into_memory()

    def set_client(self, client: aioredis.Redis | None) -> None:
        self._client = client

    def set_file_path(self, path: Path | str | None) -> None:
        """Test/ops helper — point at a durable JSON file."""
        self._file_path = Path(path) if path else None
        if self._file_path is not None:
            self._load_file_into_memory()

    def _key(self, tenant_id: str, seller_id: str) -> str:
        return f"{KYB_PREFIX}{tenant_id.strip()}:{seller_id.strip()}"

    def clear_memory_for_tests(self) -> None:
        with self._lock:
            self._memory.clear()
        if self._file_path is not None and self._file_path.is_file():
            try:
                self._file_path.unlink()
            except OSError:
                pass

    def _load_file_into_memory(self) -> None:
        path = self._file_path
        if path is None or not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                with self._lock:
                    for k, v in data.items():
                        if isinstance(v, dict):
                            self._memory[str(k)] = dict(v)
        except (OSError, json.JSONDecodeError):
            log.warning("kyb_store_file_load_failed path=%s", path, exc_info=True)

    def _persist_file(self) -> None:
        path = self._file_path
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                payload = {k: dict(v) for k, v in self._memory.items()}
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, default=str), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            log.warning("kyb_store_file_persist_failed path=%s", path, exc_info=True)

    async def get(self, tenant_id: str, seller_id: str) -> dict[str, Any] | None:
        key = self._key(tenant_id, seller_id)
        if self._client is not None:
            try:
                raw = await self._client.get(key)
                if raw:
                    data = json.loads(raw)
                    if isinstance(data, dict):
                        return data
            except Exception:
                log.warning("kyb_store_redis_get_failed key=%s", key, exc_info=True)
        with self._lock:
            row = self._memory.get(key)
            return dict(row) if row else None

    async def put(self, tenant_id: str, seller_id: str, record: dict[str, Any]) -> dict[str, Any]:
        key = self._key(tenant_id, seller_id)
        payload = dict(record)
        payload["tenant_id"] = tenant_id.strip()
        payload["seller_id"] = seller_id.strip()
        encoded = json.dumps(payload, default=str)
        if self._client is not None:
            try:
                await self._client.setex(key, KYB_TTL_SECONDS, encoded)
            except Exception:
                log.warning("kyb_store_redis_put_failed key=%s", key, exc_info=True)
        with self._lock:
            self._memory[key] = dict(payload)
        self._persist_file()
        return dict(payload)

    def backend(self) -> str:
        if self._client is not None:
            return "redis"
        if self._file_path is not None:
            return "file"
        return "memory"

    def list_memory_records(self) -> list[dict[str, Any]]:
        """Rescreen cadence uses memory/file snapshot (Redis SCAN not required).

        ponytail: Redis multi-key listing deferred; file/memory covers CI + single-node.
        """
        with self._lock:
            return [dict(v) for v in self._memory.values()]


kyb_store = MarketplaceKybStore()
