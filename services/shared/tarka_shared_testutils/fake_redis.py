"""In-memory Redis fake shared by service test suites."""

from __future__ import annotations


class FakeRedis:
    """Minimal in-memory fake for testing sorted set operations."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, float]] = {}

    def pipeline(self) -> "FakePipeline":
        return FakePipeline(self)

    async def zcount(self, key: str, min_score: float | str, max_score: float | str) -> int:
        d = self._data.get(key, {})
        if isinstance(min_score, str) and min_score == "-inf":
            min_score = float("-inf")
        if isinstance(max_score, str) and max_score == "+inf":
            max_score = float("inf")
        return sum(1 for v in d.values() if float(min_score) <= v <= float(max_score))

    async def zrangebyscore(
        self, key: str, min_score: float | str, max_score: float | str
    ) -> list[str]:
        d = self._data.get(key, {})
        if isinstance(min_score, str) and min_score == "-inf":
            min_score = float("-inf")
        if isinstance(max_score, str) and max_score == "+inf":
            max_score = float("inf")
        return [k for k, v in d.items() if float(min_score) <= v <= float(max_score)]

    async def aclose(self) -> None:
        """Async close hook for redis.asyncio compatibility."""
        return


class FakePipeline:
    """Collect and replay fake Redis pipeline operations."""

    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis
        self._ops: list[tuple[str, str, dict[str, float]]] = []

    def zadd(self, key: str, mapping: dict[str, float]) -> "FakePipeline":
        self._ops.append(("zadd", key, mapping))
        return self

    def expire(self, key: str, ttl: int) -> "FakePipeline":
        _ = (key, ttl)
        return self

    async def execute(self) -> None:
        for op, key, mapping in self._ops:
            if op == "zadd":
                self._redis._data.setdefault(key, {}).update(mapping)
