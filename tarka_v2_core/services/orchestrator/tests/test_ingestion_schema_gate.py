"""Gate: strict ``IngestionSchema`` + ``POST /ingest`` → **400** on malformed bodies."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from tests.test_anumana_browser_ingest import _FakeRedis

_SRC_ORCH = Path(__file__).resolve().parents[1] / "src"
_SRC_INGESTOR = Path(__file__).resolve().parents[2] / "ingestor" / "src"
for _p in (_SRC_ORCH, _SRC_INGESTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_ingestion_schema_accepts_valid_canvas_hex() -> None:
    from orchestrator.ingestion_schema import IngestionSchema

    m = IngestionSchema.model_validate(
        {"canvas_fingerprint": "ab" * 32},
    )
    assert m.canvas_fingerprint == "ab" * 32


def test_ingestion_schema_rejects_unknown_field() -> None:
    from orchestrator.ingestion_schema import IngestionSchema

    with pytest.raises(ValidationError):
        IngestionSchema.model_validate(
            {"canvas_fingerprint": "ab" * 32, "evil": True},
        )


def test_post_ingest_returns_400_extra_field() -> None:
    from orchestrator.main import create_app  # noqa: E402

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        anumana_redis_client=_FakeRedis(),
    )
    with TestClient(app) as client:
        r = client.post(
            "/ingest",
            json={
                "canvas_fingerprint": "ab" * 32,
                "unexpected_key": 1,
            },
        )
    assert r.status_code == 400
    body = r.json()
    assert body.get("error") == "invalid_ingestion_payload"
    assert "detail" in body


def test_post_ingest_returns_400_bad_ip() -> None:
    from orchestrator.main import create_app  # noqa: E402

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        anumana_redis_client=_FakeRedis(),
    )
    with TestClient(app) as client:
        r = client.post(
            "/ingest",
            json={
                "canvas_fingerprint": "ab" * 32,
                "ip": "not-a-valid-ip",
            },
        )
    assert r.status_code == 400


def test_post_ingest_returns_400_non_hex_canvas() -> None:
    from orchestrator.main import create_app  # noqa: E402

    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        anumana_redis_client=_FakeRedis(),
    )
    with TestClient(app) as client:
        r = client.post(
            "/ingest",
            json={"canvas_fingerprint": "zz" * 32},
        )
    assert r.status_code == 400


def test_post_ingest_telemetry_packet_only_ok() -> None:
    from orchestrator.main import create_app  # noqa: E402

    fake = _FakeRedis()
    app = create_app(
        rule_engine_url="http://rules.test",
        shadow_agent_url=None,
        anumana_redis_client=fake,
    )
    enc = "abcd1234" + "x" * 24
    digest = "a" * 64
    with TestClient(app) as client:
        r = client.post(
            "/ingest",
            json={
                "telemetry_packet": {"v": 1, "enc": enc, "int": digest},
            },
        )
    assert r.status_code == 200, r.text
    assert r.json().get("accepted") is True
