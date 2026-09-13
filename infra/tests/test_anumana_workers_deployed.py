"""Gate: the anumana workers are deployable, not manual CLIs.

The duck sink and SDK heartbeat monitor shipped as undeployed manual workers —
telemetry accumulated in Redis with nothing draining it (and no LTRIM cap on
the producer side). This gate fails when either worker disappears from the
full compose, or when the duck sink is deployed without a persisted DuckDB
path — the sink must not RPOP telemetry into an in-memory database that dies
with the container.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
FULL = REPO / "infra" / "deploy" / "docker-compose.yml"


def test_duck_sink_deployed_with_persisted_duckdb() -> None:
    doc = yaml.safe_load(FULL.read_text(encoding="utf-8"))
    svc = doc["services"]["anumana-duck-sink"]
    assert svc["command"] == ["-m", "workers.anumana_nats_duck_sink"], (
        "duck sink must run the worker module"
    )
    env_raw = svc["environment"]
    if isinstance(env_raw, dict):
        env_map = dict(env_raw)
    else:
        env_map = {e.split("=", 1)[0]: e.split("=", 1)[1] for e in env_raw}
    assert env_map.get("ORCHESTRATOR_LOCAL_ANALYTICS_DUCKDB", "").startswith("/data/"), (
        "duck sink must persist its DuckDB under a named volume mount"
    )
    mounts = svc.get("volumes", [])
    sources = {v["source"] for v in mounts if isinstance(v, dict)} | {
        v.split(":", 1)[0] for v in mounts if isinstance(v, str)
    }
    assert "anumana_duck" in sources, "duck sink must mount the anumana_duck named volume"


def test_heartbeat_monitor_deployed() -> None:
    doc = yaml.safe_load(FULL.read_text(encoding="utf-8"))
    svc = doc["services"]["anumana-heartbeat-monitor"]
    assert svc["command"] == ["-m", "workers.sdk_heartbeat_monitor"]


if __name__ == "__main__":
    test_duck_sink_deployed_with_persisted_duckdb()
    test_heartbeat_monitor_deployed()
    print("ok")
