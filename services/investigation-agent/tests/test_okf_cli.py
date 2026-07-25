"""CLI smoke tests for OKF staging export and validation."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from tests.okf_provenance_helpers import attach_concept_provenance

_REPO_ROOT = Path(__file__).resolve().parents[3]
_AGENT_ROOT = _REPO_ROOT / "services" / "investigation-agent"
_RULES_DIR = _REPO_ROOT / "services" / "decision-api" / "rules"


def _run_export(
    output: Path, *, include_playbooks: bool = True
) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(_AGENT_ROOT / "scripts" / "export_okf_bundle.py"),
        "--rules-dir",
        str(_RULES_DIR),
        "--output",
        str(output),
    ]
    if include_playbooks:
        cmd.append("--include-playbooks")
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _run_landmark_export(
    input_path: Path,
    output: Path,
    *,
    tenant_id: str = "t1",
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(_AGENT_ROOT / "scripts" / "export_okf_bundle.py"),
            "--landmark-input",
            str(input_path),
            "--tenant-id",
            tenant_id,
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _run_validate(
    root: Path,
    *,
    scope: str = "shared",
    tenant_id: str = "",
    shared_root: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(_AGENT_ROOT / "scripts" / "validate_okf_bundle.py"),
        str(root),
        "--scope",
        scope,
    ]
    if tenant_id:
        cmd.extend(["--tenant-id", tenant_id])
    if shared_root is not None:
        cmd.extend(["--shared-root", str(shared_root)])
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def test_export_cli_writes_staging_bundle(tmp_path: Path) -> None:
    output = tmp_path / "okf-staging" / "shared"
    result = _run_export(output)
    assert result.returncode == 0, result.stderr
    assert (output / "rules").is_dir()
    assert any(output.rglob("*.md"))


def test_validate_staging_shared_bundle_rejects_proposed(tmp_path: Path) -> None:
    output = tmp_path / "okf-staging" / "shared"
    assert _run_export(output).returncode == 0
    result = _run_validate(output, scope="shared")
    assert result.returncode == 1
    issues = json.loads(result.stdout)
    codes = {item["code"] for item in issues}
    assert "approval_status_not_approved" in codes


def test_export_cli_refuses_active_shared_root(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    active = repo / "knowledge" / "shared"
    active.mkdir(parents=True)
    env = os.environ.copy()
    env["OKF_REPO_ROOT"] = str(repo)
    cmd = [
        sys.executable,
        str(_AGENT_ROOT / "scripts" / "export_okf_bundle.py"),
        "--rules-dir",
        str(_RULES_DIR),
        "--output",
        str(active),
        "--include-playbooks",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
    assert result.returncode == 1
    assert "active" in result.stderr.lower()


def test_landmark_cli_writes_concept_snapshot_and_manifest(tmp_path: Path) -> None:
    source = tmp_path / "landmark.json"
    source.write_text(
        json.dumps(
            {
                "case_id": "case-cli-1",
                "title": "Money Mule Review",
                "summary": "Sanitized transaction pattern.",
                "lessons": "Manual Review remains required.",
                "approved_revision": "review-rev-1",
                "evidence_ids": ["ev-pseudonymous-1"],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "okf-staging" / "tenants" / "t1"

    result = _run_landmark_export(source, output)

    assert result.returncode == 0, result.stderr
    concept = output / "landmark-cases" / "case-cli-1.md"
    manifest = json.loads((output / "source-manifest.json").read_text())
    entry = manifest["sources"]["landmark-cases/case-cli-1"]
    snapshot = output / entry["snapshot_path"]
    assert concept.is_file()
    assert snapshot.is_file()
    assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == entry["source_content_hash"]


def test_landmark_cli_rejects_pii_and_manual_source_hash(tmp_path: Path) -> None:
    output = tmp_path / "okf-staging" / "tenants" / "t1"
    for name, payload in (
        (
            "pii",
            {
                "case_id": "case-cli-pii",
                "title": "JANE EXAMPLE",
            },
        ),
        (
            "manual-hash",
            {
                "case_id": "case-cli-hash",
                "title": "Reviewed case",
                "source_content_hash": "a" * 64,
            },
        ),
    ):
        source = tmp_path / f"{name}.json"
        source.write_text(json.dumps(payload), encoding="utf-8")
        result = _run_landmark_export(source, output)
        assert result.returncode == 1
        assert "pii" in result.stderr.lower() or "source_content_hash" in result.stderr


def test_validate_active_knowledge_shared_index_only(tmp_path: Path) -> None:
    """Committed active root with only index.md remains valid."""
    root = _REPO_ROOT / "knowledge" / "shared"
    if not root.is_dir():
        pytest.skip("knowledge/shared not present")
    result = _run_validate(root, scope="shared")
    assert result.returncode == 0, result.stdout + result.stderr


def _approved_frontmatter(*, tenant_scope: str, source_hash_char: str) -> str:
    return (
        "---\n"
        "type: Reference\n"
        f"tenant_scope: {tenant_scope}\n"
        "source_uri: docs/ref\n"
        f"source_content_hash: {source_hash_char * 64}\n"
        "approval_status: approved\n"
        "approved_revision: approved-rev-1\n"
        "sensitivity: internal\n"
        "---\n"
    )


def test_validate_tenant_bundle_accepts_shared_root_for_logical_links(
    tmp_path: Path,
) -> None:
    shared = tmp_path / "shared"
    tenant = tmp_path / "tenants" / "t1"
    (shared / "rules").mkdir(parents=True)
    (tenant / "playbooks").mkdir(parents=True)
    (shared / "index.md").write_text('---\nokf_version: "0.1"\n---\n')
    (tenant / "index.md").write_text('---\nokf_version: "0.1"\n---\n')
    shared_concept = shared / "rules" / "high-amount.md"
    shared_concept.write_text(
        _approved_frontmatter(tenant_scope="shared", source_hash_char="a") + "Shared rule body.\n",
        encoding="utf-8",
    )
    tenant_concept = tenant / "playbooks" / "review.md"
    tenant_concept.write_text(
        _approved_frontmatter(tenant_scope="t1", source_hash_char="b")
        + "Follow [high amount](/shared/rules/high-amount.md).\n",
        encoding="utf-8",
    )
    attach_concept_provenance(
        shared,
        shared_concept,
        source_record={"fixture": "shared-high-amount"},
    )
    attach_concept_provenance(
        tenant,
        tenant_concept,
        source_record={"fixture": "tenant-review"},
    )

    result = _run_validate(
        tenant,
        scope="tenant",
        tenant_id="t1",
        shared_root=shared,
    )

    assert result.returncode == 0, result.stdout + result.stderr
