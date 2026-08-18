"""Helm honesty: local-sqlite forbids replicaCount>1; postgres allows it."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CHART = ROOT / "infra/deploy/helm/fraud-stack"


def _helm(*args: str) -> subprocess.CompletedProcess[str]:
    helm = shutil.which("helm")
    if not helm:
        pytest.skip("helm not installed")
    return subprocess.run(
        [helm, *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def _agent_docs(rendered: str) -> list[str]:
    docs: list[str] = []
    current: list[str] = []
    for line in rendered.splitlines():
        if line.strip() == "---":
            if current:
                docs.append("\n".join(current))
            current = []
            continue
        current.append(line)
    if current:
        docs.append("\n".join(current))
    return [d for d in docs if "investigation-agent" in d]


def test_helm_sqlite_replica_count_2_fails() -> None:
    result = _helm(
        "template",
        "tarka",
        str(CHART),
        "--set",
        "investigationAgent.enabled=true",
        "--set",
        "investigationAgent.replicaCount=2",
        "--set",
        "investigationAgent.dataPersistence.mode=local-sqlite",
    )
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "local-sqlite" in combined


def test_helm_postgres_replica_count_2_templates() -> None:
    result = _helm(
        "template",
        "tarka",
        str(CHART),
        "--set",
        "investigationAgent.enabled=true",
        "--set",
        "investigationAgent.replicaCount=2",
        "--set",
        "investigationAgent.dataPersistence.mode=postgres",
        "--set",
        "global.externalServices.postgres.enabled=true",
        "--set",
        "global.externalServices.postgres.databaseUrl=postgresql://fraud:pw@db.internal:5432/fraud",
        "--set",
        "postgres.enabled=false",
    )
    assert result.returncode == 0, result.stderr
    docs = _agent_docs(result.stdout)
    assert docs, "expected investigation-agent manifests"
    joined = "\n---\n".join(docs)
    assert "INVESTIGATION_STORE" in joined
    assert "postgres" in joined
    assert "RollingUpdate" in joined
    assert "replicas: 2" in joined
    assert "DATABASE_URL" in joined
    assert "kind: PersistentVolumeClaim" not in joined
    deploy = next(d for d in docs if "kind: Deployment" in d)
    assert "type: Recreate" not in deploy
    assert "emptyDir: {}" in deploy
