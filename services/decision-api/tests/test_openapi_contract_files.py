"""Validate checked-in OpenAPI specs and FastAPI app schema alignment."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from openapi_spec_validator import validate

_REPO_ROOT = Path(__file__).resolve().parents[3]
_OPENAPI_DIR = _REPO_ROOT / "contracts" / "openapi"


@pytest.mark.parametrize(
    "path",
    sorted(_OPENAPI_DIR.glob("*.yaml")),
)
def test_openapi_yaml_parses_and_validates_oas31(path: Path):
    """Checked-in contracts must parse as YAML, declare core fields, and satisfy OpenAPI 3.1 schema."""
    name = path.name
    assert path.is_file(), f"missing {path}"
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(spec, dict), f"{name}: root must be a mapping"
    assert spec.get("openapi"), f"{name}: missing openapi version field"
    assert spec.get("info", {}).get("title"), f"{name}: missing info.title"
    paths = spec.get("paths")
    assert isinstance(paths, dict) and paths, f"{name}: missing non-empty paths"
    validate(spec)


def test_fastapi_openapi_contains_evaluate_and_inference():
    # Load submodule so patch("decision_api.main....") resolves (pkgutil.getattr).
    import decision_api.main  # noqa: F401

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL", "sqlite+aiosqlite:///")
        mp.setenv("REDIS_URL", "redis://localhost:6379/0")
        mp.setenv("API_KEYS", "")
        with patch("decision_api.main.init_db", new_callable=AsyncMock):
            with patch("decision_api.main.redis_tags") as mock_redis:
                mock_redis.connect = AsyncMock()
                mock_redis.close = AsyncMock()
                mock_redis._client = MagicMock()
                mock_redis.get_tags = AsyncMock(return_value=[])
                mock_redis.merge_tags = AsyncMock(return_value=[])
                mock_redis.set_cached_score = AsyncMock()
                mock_redis.store_nonce = AsyncMock()
                mock_redis.consume_nonce = AsyncMock(return_value=True)
                mock_redis.check_and_store_replay_signature = AsyncMock(return_value=False)
                with patch("decision_api.main.load_rules"):
                    with patch("decision_api.main.agg_store") as mock_agg:
                        mock_agg._client = None
                        from decision_api.main import app

                        schema = app.openapi()
                        paths = schema.get("paths", {})
                        assert "/v1/decisions/evaluate" in paths, "FastAPI schema should expose POST evaluate"
                        assert "/v1/challenge-policies" in paths, "FastAPI schema should expose GET challenge-policies"
                        assert "/v1/internal/counters/manifest" in paths
                        assert "/v1/internal/counters/catalog" in paths
                        assert "/v1/internal/counters/definitions" in paths
                        assert "/v1/internal/counters/replay" in paths
                        assert "/v1/internal/counters/replay/from-audit" in paths
                        assert "/v1/ops/calibration-status" in paths
                        assert "/v1/slo" in paths
                        schemes = schema.get("components", {}).get("securitySchemes", {})
                        assert "TarkaCounterReplayToken" in schemes
                        replay_post = paths["/v1/internal/counters/replay"].get("post", {})
                        assert replay_post.get("security") == [{"TarkaCounterReplayToken": []}]
                        blob = json.dumps(schema)
                        assert "inference_context" in blob.lower()
                        assert "calibration_profile_version" in blob
                        assert "location_confidence" in blob
                        assert "confidence_sources" in blob
