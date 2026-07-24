"""End-to-end OKF gates for activation, retrieval, fallback, and packaging."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from investigation_agent import knowledge_db
from investigation_agent.citation_schema import build_standard_citations
from investigation_agent.knowledge_db import (
    ingest_document_sync,
    index_okf_concepts_sync,
    reset_connection_for_tests,
)
from investigation_agent.knowledge_store import retrieve_knowledge_async
from investigation_agent.okf_parser import validate_bundle
from investigation_agent.okf_registry import OkfRegistry

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _write_index(root: Path, heading: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.md").write_text(
        f'---\nokf_version: "0.1"\n---\n# {heading}\n',
        encoding="utf-8",
    )


def _approved_frontmatter(
    *,
    concept_type: str,
    title: str,
    tenant_scope: str,
    source_uri: str,
    source_hash_char: str,
    tags: tuple[str, ...] = (),
    evidence_ids: tuple[str, ...] = (),
) -> str:
    lines = [
        "---",
        f"type: {concept_type}",
        f"title: {title}",
    ]
    if tags:
        lines.append("tags:")
        lines.extend(f"  - {tag}" for tag in tags)
    lines.extend(
        [
            f"tenant_scope: {tenant_scope}",
            f"source_uri: {source_uri}",
            f"source_content_hash: {source_hash_char * 64}",
            "approval_status: approved",
            "approved_revision: approved-rev-1",
            "sensitivity: internal",
        ]
    )
    if evidence_ids:
        lines.append("evidence_ids:")
        lines.extend(f"  - {evidence_id}" for evidence_id in evidence_ids)
    return "\n".join([*lines, "---", ""])


def _write_concept(
    root: Path,
    rel_path: str,
    *,
    concept_type: str,
    title: str,
    tenant_scope: str,
    source_uri: str,
    source_hash_char: str,
    tags: tuple[str, ...] = (),
    evidence_ids: tuple[str, ...] = (),
    body: str,
) -> None:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _approved_frontmatter(
            concept_type=concept_type,
            title=title,
            tenant_scope=tenant_scope,
            source_uri=source_uri,
            source_hash_char=source_hash_char,
            tags=tags,
            evidence_ids=evidence_ids,
        )
        + body.rstrip()
        + "\n",
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def isolated_knowledge_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INVESTIGATION_DATA_DIR", str(tmp_path / "rag"))
    monkeypatch.setenv("KNOWLEDGE_TTL_SECONDS", "86400")
    reset_connection_for_tests()
    yield
    reset_connection_for_tests()


def _build_bundle_tree(shared_root: Path, tenant_root: Path) -> None:
    _write_index(shared_root, "Shared approved OKF")
    _write_concept(
        shared_root,
        "rules/high-amount.md",
        concept_type="Fraud Rule",
        title="High Amount Rule",
        tenant_scope="shared",
        source_uri="rules/default.json#high-amount",
        source_hash_char="a",
        tags=("high-amount",),
        body="Default shared high amount threshold guidance.",
    )
    _write_concept(
        shared_root,
        "references/kyc-checklist.md",
        concept_type="Reference",
        title="KYC Checklist",
        tenant_scope="shared",
        source_uri="references/kyc-checklist.json",
        source_hash_char="b",
        body="Confirm profile, address, and expected account activity.",
    )

    t1 = tenant_root / "t1"
    _write_index(t1, "Tenant t1 approved OKF")
    _write_concept(
        t1,
        "rules/high-amount.md",
        concept_type="Fraud Rule",
        title="High Amount Rule",
        tenant_scope="t1",
        source_uri="rules/t1/high-amount.json",
        source_hash_char="c",
        tags=("high-amount",),
        evidence_ids=("ev-rule",),
        body=(
            "Tenant t1 high amount rule.\n\n"
            "Run [High Amount Review Playbook](../playbooks/high-amount-review.md) "
            "and verify [KYC Checklist](/shared/references/kyc-checklist.md)."
        ),
    )
    _write_concept(
        t1,
        "playbooks/high-amount-review.md",
        concept_type="Investigation Playbook",
        title="High Amount Review Playbook",
        tenant_scope="t1",
        source_uri="playbooks/t1/high-amount-review.json",
        source_hash_char="d",
        tags=("playbook",),
        evidence_ids=("ev-playbook",),
        body="Review customer profile, transaction velocity, and chargeback history.",
    )

    t2 = tenant_root / "t2"
    _write_index(t2, "Tenant t2 approved OKF")
    _write_concept(
        t2,
        "playbooks/t2-secret.md",
        concept_type="Investigation Playbook",
        title="T2 Secret Playbook",
        tenant_scope="t2",
        source_uri="playbooks/t2/secret.json",
        source_hash_char="e",
        tags=("t2-secret",),
        body="Tenant t2 only handling instructions.",
    )


def _activate_and_index(shared_root: Path, tenant_root: Path) -> OkfRegistry:
    shared_validation = validate_bundle(shared_root, scope="shared", tenant_id=None)
    assert shared_validation.valid is True
    assert shared_validation.bundle is not None
    index_okf_concepts_sync(shared_validation.bundle)

    for tenant_id in ("t1", "t2"):
        validation = validate_bundle(
            tenant_root / tenant_id,
            scope="tenant",
            tenant_id=tenant_id,
            shared_bundle=shared_validation.bundle,
        )
        assert validation.valid is True
        assert validation.bundle is not None
        index_okf_concepts_sync(validation.bundle)

    registry = OkfRegistry(shared_root=shared_root, tenant_root=tenant_root)
    reload_result = registry.reload()
    assert reload_result.activated is True
    return registry


@pytest.mark.asyncio
async def test_exact_link_rag_fallback_isolation_rollback_and_citations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_root = tmp_path / "shared"
    tenant_root = tmp_path / "tenants"
    _build_bundle_tree(shared_root, tenant_root)
    registry = _activate_and_index(shared_root, tenant_root)
    prior_revision = registry.snapshot_revision("t1")

    ingest_document_sync(
        "t1",
        "analyst-1",
        "Residual high amount memo",
        "Residual chargeback memo for high amount rule escalation and manual review.",
    )

    async def fail_embeddings(*_: Any, **__: Any) -> list[list[float]]:
        raise RuntimeError("embedding service unavailable")

    monkeypatch.setattr(knowledge_db.emb_mod, "embed_texts", fail_embeddings)

    result = await retrieve_knowledge_async(
        object(),
        registry=registry,
        use_embeddings=True,
        api_key="test-key",
        base_url="http://embeddings.local/v1",
        embed_model="test-embedding",
        tenant_id="t1",
        analyst_id="analyst-1",
        query="High Amount Rule",
        limit=4,
    )

    assert result.retrieval_mode == "exact+expand+keyword_fallback"
    assert [item.concept_id for item in result.results] == [
        "rules/high-amount",
        "playbooks/high-amount-review",
        "references/kyc-checklist",
        None,
    ]
    assert [item.authority for item in result.results] == [
        "tenant_okf",
        "tenant_okf",
        "shared_okf",
        "memo_rag",
    ]
    assert result.results[1].retrieval_path == (
        "rules/high-amount",
        "playbooks/high-amount-review",
    )

    allowed_concepts = {item.concept_id for item in result.results if item.concept_id}
    allowed_evidence = {evidence_id for item in result.results for evidence_id in item.evidence_ids}
    citations, summary = build_standard_citations(
        claims=[
            {
                "text": "Use the high amount rule and linked playbook.",
                "source": "tool",
                "concept_ids": ["rules/high-amount", "playbooks/high-amount-review"],
                "evidence_ids": ["ev-rule", "ev-playbook"],
            }
        ],
        deterministic_support=[{"claim_index": 0, "supported": True}],
        allowed_concept_ids=allowed_concepts,
        allowed_evidence_ids=allowed_evidence,
    )
    resolved = {(item["artifact"], item["id"]) for item in citations[0]["resolves_to"]}
    assert summary.supported_count == 1
    assert ("okf_concept", "rules/high-amount") in resolved
    assert ("okf_concept", "playbooks/high-amount-review") in resolved
    assert ("evidence", "ev-rule") in resolved
    assert ("evidence", "ev-playbook") in resolved

    t2_result = await retrieve_knowledge_async(
        object(),
        registry=registry,
        use_embeddings=True,
        api_key="test-key",
        base_url="http://embeddings.local/v1",
        embed_model="test-embedding",
        tenant_id="t1",
        analyst_id="analyst-1",
        query="T2 Secret Playbook",
        limit=5,
    )
    assert "playbooks/t2-secret" not in {item.concept_id for item in t2_result.results}

    (shared_root / "rules" / "high-amount.md").write_text("invalid\n", encoding="utf-8")
    rollback = registry.reload()
    assert rollback.activated is False
    assert registry.snapshot_revision("t1") == prior_revision
    assert registry.resolve("t1", "High Amount Rule")


def test_deployment_config_ships_only_shared_bundle_and_mounts_tenants() -> None:
    dockerfile = (_REPO_ROOT / "services" / "investigation-agent" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    env_reference = (
        _REPO_ROOT / "services" / "investigation-agent" / ".env.reference.example"
    ).read_text(encoding="utf-8")

    assert "COPY knowledge/shared /app/knowledge/shared" in dockerfile
    assert "OKF_SHARED_ROOT=/app/knowledge/shared" in dockerfile
    assert "OKF_TENANT_ROOT=/var/lib/tarka/knowledge/tenants" in dockerfile
    assert "COPY knowledge/tenants" not in dockerfile
    assert "OKF_ENABLED=true" in env_reference
    assert "OKF_SHARED_ROOT=/app/knowledge/shared" in env_reference
    assert "OKF_TENANT_ROOT=/var/lib/tarka/knowledge/tenants" in env_reference
    assert "OKF_MAX_LINK_DEPTH=2" in env_reference
    assert "OKF_MAX_CONCEPTS=24" in env_reference
