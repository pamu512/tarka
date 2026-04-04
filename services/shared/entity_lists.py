"""Storage-agnostic entity whitelist, blacklist, and test bypass lists.

Supports pluggable backends:
- memory: In-process dict (dev/testing)
- redis: Redis hash-based (production, shared across instances)
- postgres: SQLAlchemy-based (durable, audit-friendly)
- file: JSON file on disk (simple single-instance)
- api: External HTTP API (third-party integration)

Usage:
    store = create_list_store("redis", redis_url="redis://localhost:6379/0")
    await store.connect()
    await store.add("whitelist", "tenant1", "entity123", reason="VIP customer", created_by="admin")
    result = await store.check("tenant1", "entity123")
    # result = ListCheckResult(list_type="whitelist", reason="VIP customer", ...)
"""

import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

log = logging.getLogger(__name__)

ListType = Literal["whitelist", "blacklist", "test_bypass"]
ALL_LIST_TYPES: tuple[ListType, ...] = ("whitelist", "blacklist", "test_bypass")


@dataclass
class ListEntry:
    list_type: ListType
    tenant_id: str
    entity_id: str
    reason: str = ""
    created_by: str = "system"
    expires_at: str | None = None  # ISO datetime or None for permanent
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        try:
            exp = datetime.fromisoformat(self.expires_at)
            return datetime.now(timezone.utc) > exp
        except (ValueError, TypeError):
            return False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ListEntry":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ListCheckResult:
    found: bool
    list_type: ListType | None = None
    action: str = "evaluate"  # "allow", "deny", "evaluate" (test_bypass evaluates but overrides decision)
    reason: str = ""
    entry: ListEntry | None = None


class ListStore(ABC):
    """Abstract base for entity list storage."""

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def add(self, list_type: ListType, tenant_id: str, entity_id: str, **kwargs) -> ListEntry: ...

    @abstractmethod
    async def remove(self, list_type: ListType, tenant_id: str, entity_id: str) -> bool: ...

    @abstractmethod
    async def check(self, tenant_id: str, entity_id: str) -> ListCheckResult: ...

    @abstractmethod
    async def get_all(self, list_type: ListType, tenant_id: str, limit: int = 200) -> list[ListEntry]: ...

    @abstractmethod
    async def get_entry(self, list_type: ListType, tenant_id: str, entity_id: str) -> ListEntry | None: ...

    @abstractmethod
    async def count(self, list_type: ListType, tenant_id: str) -> int: ...

    def _build_result(self, entry: ListEntry | None) -> ListCheckResult:
        if not entry or entry.is_expired():
            return ListCheckResult(found=False, action="evaluate")
        action_map: dict[ListType, str] = {
            "whitelist": "allow",
            "blacklist": "deny",
            "test_bypass": "evaluate",
        }
        return ListCheckResult(
            found=True,
            list_type=entry.list_type,
            action=action_map.get(entry.list_type, "evaluate"),
            reason=entry.reason,
            entry=entry,
        )


# ── Memory Backend ───────────────────────────────────────────────────


class MemoryListStore(ListStore):
    def __init__(self):
        self._data: dict[str, ListEntry] = {}

    def _key(self, list_type: str, tenant_id: str, entity_id: str) -> str:
        return f"{list_type}:{tenant_id}:{entity_id}"

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        self._data.clear()

    async def add(self, list_type: ListType, tenant_id: str, entity_id: str, **kwargs) -> ListEntry:
        entry = ListEntry(list_type=list_type, tenant_id=tenant_id, entity_id=entity_id, **kwargs)
        self._data[self._key(list_type, tenant_id, entity_id)] = entry
        return entry

    async def remove(self, list_type: ListType, tenant_id: str, entity_id: str) -> bool:
        return self._data.pop(self._key(list_type, tenant_id, entity_id), None) is not None

    async def check(self, tenant_id: str, entity_id: str) -> ListCheckResult:
        for lt in ("blacklist", "whitelist", "test_bypass"):
            entry = self._data.get(self._key(lt, tenant_id, entity_id))
            if entry and not entry.is_expired():
                return self._build_result(entry)
        return ListCheckResult(found=False, action="evaluate")

    async def get_all(self, list_type: ListType, tenant_id: str, limit: int = 200) -> list[ListEntry]:
        prefix = f"{list_type}:{tenant_id}:"
        entries = [e for k, e in self._data.items() if k.startswith(prefix) and not e.is_expired()]
        return entries[:limit]

    async def get_entry(self, list_type: ListType, tenant_id: str, entity_id: str) -> ListEntry | None:
        entry = self._data.get(self._key(list_type, tenant_id, entity_id))
        return entry if entry and not entry.is_expired() else None

    async def count(self, list_type: ListType, tenant_id: str) -> int:
        prefix = f"{list_type}:{tenant_id}:"
        return sum(1 for k, e in self._data.items() if k.startswith(prefix) and not e.is_expired())


# ── Redis Backend ────────────────────────────────────────────────────


class RedisListStore(ListStore):
    def __init__(self, redis_url: str):
        self._url = redis_url
        self._client = None

    def _key(self, list_type: str, tenant_id: str) -> str:
        return f"tarka:lists:{list_type}:{tenant_id}"

    async def connect(self) -> None:
        if self._client is None:
            import redis.asyncio as aioredis

            self._client = aioredis.from_url(self._url, decode_responses=True)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def add(self, list_type: ListType, tenant_id: str, entity_id: str, **kwargs) -> ListEntry:
        await self.connect()
        entry = ListEntry(list_type=list_type, tenant_id=tenant_id, entity_id=entity_id, **kwargs)
        await self._client.hset(self._key(list_type, tenant_id), entity_id, json.dumps(entry.to_dict()))
        return entry

    async def remove(self, list_type: ListType, tenant_id: str, entity_id: str) -> bool:
        await self.connect()
        return bool(await self._client.hdel(self._key(list_type, tenant_id), entity_id))

    async def check(self, tenant_id: str, entity_id: str) -> ListCheckResult:
        await self.connect()
        for lt in ("blacklist", "whitelist", "test_bypass"):
            raw = await self._client.hget(self._key(lt, tenant_id), entity_id)
            if raw:
                entry = ListEntry.from_dict(json.loads(raw))
                if not entry.is_expired():
                    return self._build_result(entry)
                else:
                    await self._client.hdel(self._key(lt, tenant_id), entity_id)
        return ListCheckResult(found=False, action="evaluate")

    async def get_all(self, list_type: ListType, tenant_id: str, limit: int = 200) -> list[ListEntry]:
        await self.connect()
        all_raw = await self._client.hgetall(self._key(list_type, tenant_id))
        entries = []
        for raw in all_raw.values():
            entry = ListEntry.from_dict(json.loads(raw))
            if not entry.is_expired():
                entries.append(entry)
        entries.sort(key=lambda e: e.created_at, reverse=True)
        return entries[:limit]

    async def get_entry(self, list_type: ListType, tenant_id: str, entity_id: str) -> ListEntry | None:
        await self.connect()
        raw = await self._client.hget(self._key(list_type, tenant_id), entity_id)
        if not raw:
            return None
        entry = ListEntry.from_dict(json.loads(raw))
        return entry if not entry.is_expired() else None

    async def count(self, list_type: ListType, tenant_id: str) -> int:
        await self.connect()
        return await self._client.hlen(self._key(list_type, tenant_id))


# ── File Backend ─────────────────────────────────────────────────────


class FileListStore(ListStore):
    def __init__(self, directory: str = "./lists"):
        self._dir = directory
        self._data: dict[str, dict[str, dict[str, ListEntry]]] = {}

    def _path(self, list_type: str) -> str:
        return os.path.join(self._dir, f"{list_type}.json")

    async def connect(self) -> None:
        os.makedirs(self._dir, exist_ok=True)
        for lt in ALL_LIST_TYPES:
            path = self._path(lt)
            if os.path.exists(path):
                with open(path, "r") as f:
                    raw = json.load(f)
                self._data[lt] = {}
                for tid, entities in raw.items():
                    self._data[lt][tid] = {eid: ListEntry.from_dict(e) for eid, e in entities.items()}
            else:
                self._data[lt] = {}

    async def _save(self, list_type: str) -> None:
        path = self._path(list_type)
        serializable = {}
        for tid, entities in self._data.get(list_type, {}).items():
            serializable[tid] = {eid: e.to_dict() for eid, e in entities.items()}
        with open(path, "w") as f:
            json.dump(serializable, f, indent=2)

    async def close(self) -> None:
        for lt in ALL_LIST_TYPES:
            await self._save(lt)

    async def add(self, list_type: ListType, tenant_id: str, entity_id: str, **kwargs) -> ListEntry:
        entry = ListEntry(list_type=list_type, tenant_id=tenant_id, entity_id=entity_id, **kwargs)
        self._data.setdefault(list_type, {}).setdefault(tenant_id, {})[entity_id] = entry
        await self._save(list_type)
        return entry

    async def remove(self, list_type: ListType, tenant_id: str, entity_id: str) -> bool:
        removed = self._data.get(list_type, {}).get(tenant_id, {}).pop(entity_id, None) is not None
        if removed:
            await self._save(list_type)
        return removed

    async def check(self, tenant_id: str, entity_id: str) -> ListCheckResult:
        for lt in ("blacklist", "whitelist", "test_bypass"):
            entry = self._data.get(lt, {}).get(tenant_id, {}).get(entity_id)
            if entry and not entry.is_expired():
                return self._build_result(entry)
        return ListCheckResult(found=False, action="evaluate")

    async def get_all(self, list_type: ListType, tenant_id: str, limit: int = 200) -> list[ListEntry]:
        entries = [e for e in self._data.get(list_type, {}).get(tenant_id, {}).values() if not e.is_expired()]
        entries.sort(key=lambda e: e.created_at, reverse=True)
        return entries[:limit]

    async def get_entry(self, list_type: ListType, tenant_id: str, entity_id: str) -> ListEntry | None:
        entry = self._data.get(list_type, {}).get(tenant_id, {}).get(entity_id)
        return entry if entry and not entry.is_expired() else None

    async def count(self, list_type: ListType, tenant_id: str) -> int:
        return sum(1 for e in self._data.get(list_type, {}).get(tenant_id, {}).values() if not e.is_expired())


# ── API Backend ──────────────────────────────────────────────────────


class APIListStore(ListStore):
    """Delegates to an external HTTP API for list management."""

    def __init__(self, base_url: str, api_key: str = ""):
        self._base = base_url.rstrip("/")
        self._api_key = api_key
        self._http = None

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._api_key:
            h["X-API-Key"] = self._api_key
        return h

    async def connect(self) -> None:
        import httpx

        self._http = httpx.AsyncClient(timeout=5.0)

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()

    async def add(self, list_type: ListType, tenant_id: str, entity_id: str, **kwargs) -> ListEntry:
        r = await self._http.post(
            f"{self._base}/lists/{list_type}",
            json={"tenant_id": tenant_id, "entity_id": entity_id, **kwargs},
            headers=self._headers(),
        )
        r.raise_for_status()
        return ListEntry.from_dict(r.json())

    async def remove(self, list_type: ListType, tenant_id: str, entity_id: str) -> bool:
        r = await self._http.delete(
            f"{self._base}/lists/{list_type}/{tenant_id}/{entity_id}",
            headers=self._headers(),
        )
        return r.status_code == 200

    async def check(self, tenant_id: str, entity_id: str) -> ListCheckResult:
        r = await self._http.get(
            f"{self._base}/lists/check/{tenant_id}/{entity_id}",
            headers=self._headers(),
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("found"):
                entry = ListEntry.from_dict(data["entry"])
                return self._build_result(entry)
        return ListCheckResult(found=False, action="evaluate")

    async def get_all(self, list_type: ListType, tenant_id: str, limit: int = 200) -> list[ListEntry]:
        r = await self._http.get(
            f"{self._base}/lists/{list_type}/{tenant_id}?limit={limit}",
            headers=self._headers(),
        )
        r.raise_for_status()
        return [ListEntry.from_dict(e) for e in r.json().get("entries", [])]

    async def get_entry(self, list_type: ListType, tenant_id: str, entity_id: str) -> ListEntry | None:
        r = await self._http.get(
            f"{self._base}/lists/{list_type}/{tenant_id}/{entity_id}",
            headers=self._headers(),
        )
        if r.status_code == 200:
            return ListEntry.from_dict(r.json())
        return None

    async def count(self, list_type: ListType, tenant_id: str) -> int:
        entries = await self.get_all(list_type, tenant_id, limit=10000)
        return len(entries)


# ── Factory ──────────────────────────────────────────────────────────


def create_list_store(
    backend: str = "memory",
    redis_url: str = "",
    file_dir: str = "./lists",
    api_url: str = "",
    api_key: str = "",
) -> ListStore:
    """Create a list store with the specified backend."""
    backend = backend.lower()
    if backend == "redis":
        if not redis_url:
            raise ValueError("redis_url is required for redis backend")
        return RedisListStore(redis_url)
    if backend == "file":
        return FileListStore(file_dir)
    if backend == "api":
        if not api_url:
            raise ValueError("api_url is required for api backend")
        return APIListStore(api_url, api_key)
    return MemoryListStore()
