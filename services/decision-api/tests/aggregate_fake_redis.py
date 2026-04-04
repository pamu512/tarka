"""Shared in-memory Redis fake for aggregate store tests."""


class FakeRedis:
    """Minimal in-memory fake for testing sorted set operations."""

    def __init__(self):
        self._data: dict[str, dict[str, float]] = {}

    def pipeline(self):
        return FakePipeline(self)

    async def zcount(self, key, min_score, max_score):
        d = self._data.get(key, {})
        if isinstance(min_score, str) and min_score == "-inf":
            min_score = float("-inf")
        if isinstance(max_score, str) and max_score == "+inf":
            max_score = float("inf")
        return sum(1 for v in d.values() if float(min_score) <= v <= float(max_score))

    async def zrangebyscore(self, key, min_score, max_score):
        d = self._data.get(key, {})
        if isinstance(min_score, str) and min_score == "-inf":
            min_score = float("-inf")
        if isinstance(max_score, str) and max_score == "+inf":
            max_score = float("inf")
        return [k for k, v in d.items() if float(min_score) <= v <= float(max_score)]


class FakePipeline:
    def __init__(self, redis: FakeRedis):
        self._redis = redis
        self._ops: list = []

    def zadd(self, key, mapping):
        self._ops.append(("zadd", key, mapping))
        return self

    def expire(self, key, ttl):
        return self

    async def execute(self):
        for op, key, mapping in self._ops:
            if op == "zadd":
                self._redis._data.setdefault(key, {}).update(mapping)
