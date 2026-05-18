"""OSS #48 parity verifier endpoint."""

from fastapi.testclient import TestClient
from feature_service.main import app

from .aggregate_fake_redis import FakeRedis


def test_parity_verify_ok_empty_redis():
    fake = FakeRedis()
    from fraud_aggregates import AggregateStore

    with TestClient(app) as client:
        client.app.state.velocity_store = AggregateStore(redis_client=fake)
        client.app.state.redis_client = fake
        r = client.post(
            "/v1/internal/parity/verify",
            json={
                "tenant_id": "t1",
                "entity_id": "e1",
                "payload": {},
                "expected": {"event_count_1h": 0.0},
                "epsilon": 0.01,
            },
        )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_parity_verify_drift_409():
    fake = FakeRedis()
    from fraud_aggregates import AggregateStore

    with TestClient(app) as client:
        client.app.state.velocity_store = AggregateStore(redis_client=fake)
        client.app.state.redis_client = fake
        r = client.post(
            "/v1/internal/parity/verify",
            json={
                "tenant_id": "t1",
                "entity_id": "e1",
                "payload": {},
                "expected": {"event_count_1h": 99.0},
                "epsilon": 0.01,
            },
        )
    assert r.status_code == 409
    assert r.json()["detail"]["ok"] is False
