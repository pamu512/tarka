"""Q2 Wave 4 unit tests."""

import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
_SHARED = _ROOT.parents[1] / "services" / "shared"
for _p in (str(_SHARED), str(_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("ALLOW_INSECURE_NO_AUTH", "true")


@pytest.mark.asyncio
async def test_drift_query_envelope():
    from decision_api.drift_query_api import drift_query

    out = await drift_query(tenant_id="tenant-a", profile="default")
    assert out["schema_id"] == "tarka.drift_query/v1"
    assert out["tenant_id"] == "tenant-a"
    assert "calibration" in out


def test_benchmark_export_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("RULES_PATH", str(tmp_path))
    from decision_api.config import settings
    from decision_api.benchmark_export_api import _append_export, _load_latest_export

    settings.rules_path = str(tmp_path)
    artifact = {
        "schema_id": "tarka.tenant_benchmark_export/v1",
        "tenant_id": "tenant-export",
        "verticals": {
            "fintech": {"events_evaluated": 200, "delta": {"f1_score": 0.01}}
        },
    }
    _append_export({"export_id": "abc123", **artifact})
    loaded = _load_latest_export("tenant-export")
    assert loaded is not None
    assert loaded["tenant_id"] == "tenant-export"
    assert loaded["export_id"] == "abc123"


def test_benchmark_run_vertical_seed42(monkeypatch, tmp_path):
    try:
        import tarka_core  # noqa: F401
        import tarka_rule_engine as tre

        tre.sync_packs_json("[]")
    except ImportError:
        pytest.skip("tarka_core / tarka_rule_engine not installed")
    except Exception as exc:
        pytest.skip(f"rust rule engine unavailable: {exc}")
    monkeypatch.setenv("RULES_PATH", str(tmp_path))
    from decision_api.config import settings
    from decision_api.benchmark_export_api import _run_vertical_benchmark

    settings.rules_path = str(tmp_path)
    artifact = _run_vertical_benchmark("tenant-export", seed=42)
    assert artifact["schema_id"] == "tarka.tenant_benchmark_export/v1"
    assert "fintech" in artifact["verticals"]


@pytest.mark.asyncio
async def test_counter_catalog_agg_key(monkeypatch):
    monkeypatch.setenv("AGG_KEY_VERSION", "ci_wave4_v1")
    from decision_api.internal_counters_api import get_counter_catalog_merged

    data = await get_counter_catalog_merged()
    assert data.get("manifest_version")
    assert data.get("agg_key_version") == "ci_wave4_v1"
