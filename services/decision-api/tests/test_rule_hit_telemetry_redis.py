"""SR-15: rule hit telemetry Redis dual-write."""

from decision_api import json_rules


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, int] = {}

    def ping(self) -> bool:
        return True

    def hincrby(self, name: str, key: str, amount: int = 1) -> int:
        self.data[key] = int(self.data.get(key, 0)) + int(amount)
        return self.data[key]

    def hgetall(self, name: str) -> dict[str, str]:
        return {k: str(v) for k, v in self.data.items()}


def test_record_and_get_prefer_redis(monkeypatch):
    monkeypatch.setenv("RULE_HIT_TELEMETRY_REDIS", "1")
    fake = _FakeRedis()
    monkeypatch.setattr(json_rules, "_rule_hit_redis_client", fake)
    monkeypatch.setattr(json_rules, "_rule_hit_redis_failed", False)
    json_rules._rule_hit_counts.clear()

    json_rules.record_rule_hit("pack.json", "r1", "rule")
    snap = json_rules.get_rule_hit_telemetry()
    assert snap["durability"] == "redis"
    assert snap["total_hits"] >= 1
    assert any(r["rule_id"] == "r1" for r in snap["rows"])


def test_force_memory_when_redis_disabled(monkeypatch):
    monkeypatch.setenv("RULE_HIT_TELEMETRY_REDIS", "0")
    monkeypatch.setattr(json_rules, "_rule_hit_redis_client", None)
    monkeypatch.setattr(json_rules, "_rule_hit_redis_failed", False)
    json_rules._rule_hit_counts.clear()

    json_rules.record_rule_hit("pack.json", "r2", "rule")
    snap = json_rules.get_rule_hit_telemetry()
    assert snap["durability"] == "process_memory"
    assert snap["since_process_start"] is True
    assert any(r["rule_id"] == "r2" for r in snap["rows"])
