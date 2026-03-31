"""Unit tests for aggregate store (requires mock or real Redis)."""
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from decision_api.aggregates import AggregateStore


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


@pytest.fixture
def store():
    fake = FakeRedis()
    s = AggregateStore(redis_client=fake)
    return s, fake


class TestRecordAndCount:
    @pytest.mark.asyncio
    async def test_record_and_count(self, store):
        s, _ = store
        now = time.time()
        await s.record_event("t1", "u1", "e1", {"amount": 100}, ts=now)
        await s.record_event("t1", "u1", "e2", {"amount": 200}, ts=now)
        await s.record_event("t1", "u1", "e3", {"amount": 50}, ts=now)
        count = await s.count("t1", "u1", 3600)
        assert count == 3

    @pytest.mark.asyncio
    async def test_count_excludes_old(self, store):
        s, _ = store
        now = time.time()
        await s.record_event("t1", "u1", "e1", {}, ts=now - 7200)
        await s.record_event("t1", "u1", "e2", {}, ts=now)
        count = await s.count("t1", "u1", 3600)
        assert count == 1


class TestSumAndAvg:
    @pytest.mark.asyncio
    async def test_sum(self, store):
        s, _ = store
        now = time.time()
        await s.record_event("t1", "u1", "e1", {"amount": 100}, ts=now)
        await s.record_event("t1", "u1", "e2", {"amount": 250}, ts=now)
        total = await s.sum_field("t1", "u1", "amount", 3600)
        assert total == 350.0

    @pytest.mark.asyncio
    async def test_avg(self, store):
        s, _ = store
        now = time.time()
        await s.record_event("t1", "u1", "e1", {"amount": 100}, ts=now)
        await s.record_event("t1", "u1", "e2", {"amount": 300}, ts=now)
        avg = await s.avg_field("t1", "u1", "amount", 3600)
        assert avg == 200.0

    @pytest.mark.asyncio
    async def test_avg_empty(self, store):
        s, _ = store
        avg = await s.avg_field("t1", "u1", "amount", 3600)
        assert avg is None


class TestDistinct:
    @pytest.mark.asyncio
    async def test_distinct_count(self, store):
        s, _ = store
        now = time.time()
        await s.record_event("t1", "u1", "e1", {"ip_address": "1.2.3.4"}, ts=now)
        await s.record_event("t1", "u1", "e2", {"ip_address": "1.2.3.4"}, ts=now)
        await s.record_event("t1", "u1", "e3", {"ip_address": "5.6.7.8"}, ts=now)
        dc = await s.distinct_count("t1", "u1", "ip_address", 3600)
        assert dc == 2


class TestComputeFeatures:
    @pytest.mark.asyncio
    async def test_compute(self, store):
        s, _ = store
        now = time.time()
        await s.record_event("t1", "u1", "e1", {"amount": 100, "ip_address": "1.1.1.1"}, ts=now)
        await s.record_event("t1", "u1", "e2", {"amount": 200, "ip_address": "2.2.2.2"}, ts=now)
        features = await s.compute_features("t1", "u1", {"amount": 300, "ip_address": "3.3.3.3"})
        assert features["event_count_1h"] == 2
        assert features["sum_amount_1h"] == 300.0
        assert features["avg_amount_1h"] == 150.0
        assert features["distinct_ip_address_24h"] == 2
