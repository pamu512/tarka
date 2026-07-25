from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA_PATH = "/var/lib/tarka/investigation-agent"


def test_compose_mounts_agent_run_database_on_named_volume() -> None:
    compose = yaml.safe_load(
        (_REPO_ROOT / "infra" / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
    )
    agent = compose["services"]["investigation-agent"]
    assert agent["environment"]["INVESTIGATION_DATA_DIR"] == _DATA_PATH
    assert f"investigation_agent_data:{_DATA_PATH}" in agent["volumes"]
    assert "investigation_agent_data" in compose["volumes"]


def test_helm_defaults_to_single_replica_local_sqlite_with_pvc() -> None:
    chart_root = _REPO_ROOT / "infra" / "deploy" / "helm" / "fraud-stack"
    values = yaml.safe_load((chart_root / "values.yaml").read_text(encoding="utf-8"))
    agent = values["investigationAgent"]
    assert agent.get("replicaCount", agent.get("replicas")) == 1
    assert agent["dataPersistence"] == {
        "mode": "local-sqlite",
        "existingClaim": "",
        "mountPath": _DATA_PATH,
        "size": "1Gi",
        "storageClassName": "",
    }

    template = (chart_root / "templates" / "investigation-agent.yaml").read_text(
        encoding="utf-8"
    )
    assert "INVESTIGATION_DATA_DIR" in template
    assert "dataPersistence.mode" in template
    assert "local-sqlite persistence requires a single replica" in template
    assert "kind: PersistentVolumeClaim" in template
    assert "persistentVolumeClaim:" in template


def test_horizontal_scaling_upgrade_path_is_documented() -> None:
    docs = (_REPO_ROOT / "docs" / "docs" / "services" / "investigation-agent.md").read_text(
        encoding="utf-8"
    )
    assert "external shared AgentRun store" in docs
    assert "replicaCount: 1" in docs


def test_helm_local_sqlite_deployments_use_recreate_rollout() -> None:
    template = (
        _REPO_ROOT
        / "infra"
        / "deploy"
        / "helm"
        / "fraud-stack"
        / "templates"
        / "investigation-agent.yaml"
    ).read_text(encoding="utf-8")

    assert "strategy:" in template
    assert "type: Recreate" in template
    assert "dataPersistence.mode" in template
