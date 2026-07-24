from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from investigation_agent.knowledge_db import reset_connection_for_tests
from investigation_agent.knowledge_store import index_okf_concepts_sync
from investigation_agent.okf_parser import validate_bundle
from investigation_agent.okf_registry import OkfRegistry
from investigation_agent.okf_retrieval import retrieve_knowledge


@dataclass(frozen=True)
class RetrievalContext:
    registry: OkfRegistry
    shared_root: Path
    tenant_root: Path
    shared_bundle: object
    tenant_bundles: dict[str, object]


def _write_index(root: Path, heading: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.md").write_text(
        "---\nokf_version: \"0.1\"\n---\n" + heading + "\n",
        encoding="utf-8",
    )


def _write_concept(
    root: Path,
    rel_path: str,
    *,
    concept_type: str,
    title: str,
    tenant_scope: str,
    source_uri: str,
    source_hash_char: str,
    description: str = "",
    tags: tuple[str, ...] = (),
    evidence_ids: tuple[str, ...] = (),
    body: str = "",
) -> None:
    lines = [
        "---",
        f"type: {concept_type}",
        f"title: {title}",
    ]
    if description:
        lines.append(f"description: {description}")
    if tags:
        lines.append("tags:")
        lines.extend(f"  - {tag}" for tag in tags)
    lines.extend(
        [
            f"source_uri: {source_uri}",
            f"source_content_hash: {source_hash_char * 64}",
            "approval_status: approved",
            f"approved_revision: {tenant_scope}-rev-1",
            "sensitivity: internal",
            f"tenant_scope: {tenant_scope}",
        ]
    )
    if evidence_ids:
        lines.append("evidence_ids:")
        lines.extend(f"  - {evidence_id}" for evidence_id in evidence_ids)
    lines.extend(["---", body.rstrip(), ""])
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _build_okf_layout(shared_root: Path, tenant_root: Path) -> None:
    _write_index(shared_root, "# Shared bundle")
    _write_concept(
        shared_root,
        "rules/high-amount.md",
        concept_type="Fraud Rule",
        title="High Amount Rule",
        description="Flags transactions above the configured threshold",
        tenant_scope="shared",
        source_uri="rules/default.json#high-amount",
        source_hash_char="a",
        tags=("high-amount", "fraud"),
        body="Transactions above the threshold require additional review.",
    )
    _write_concept(
        shared_root,
        "references/kyc-checklist.md",
        concept_type="Reference",
        title="KYC Checklist",
        description="Checklist for customer verification",
        tenant_scope="shared",
        source_uri="references/kyc-checklist.json",
        source_hash_char="b",
        tags=("kyc-checklist", "kyc"),
        body="Confirm profile, address, and expected activity.",
    )
    _write_concept(
        shared_root,
        "rules/velocity-spike.md",
        concept_type="Fraud Rule",
        title="Velocity Spike Rule",
        description="Flags sudden spikes in activity",
        tenant_scope="shared",
        source_uri="rules/default.json#velocity-spike",
        source_hash_char="c",
        tags=("velocity-spike",),
        body="Velocity spikes require analyst triage.",
    )
    _write_concept(
        shared_root,
        "guidance/conflict-a.md",
        concept_type="Reference",
        title="Conflicting Guidance",
        description="Shared guidance copy A",
        tenant_scope="shared",
        source_uri="guidance/shared-conflict.json",
        source_hash_char="d",
        body="Version A of the same shared guidance source.",
    )
    _write_concept(
        shared_root,
        "guidance/conflict-b.md",
        concept_type="Reference",
        title="Conflicting Guidance",
        description="Shared guidance copy B",
        tenant_scope="shared",
        source_uri="guidance/shared-conflict.json",
        source_hash_char="e",
        body="Version B of the same shared guidance source.",
    )

    t1_root = tenant_root / "t1"
    _write_index(t1_root, "# Tenant t1 bundle")
    _write_concept(
        t1_root,
        "playbooks/high-amount-review.md",
        concept_type="Investigation Playbook",
        title="High Amount Review Playbook",
        description="Analyst steps for high-amount cases",
        tenant_scope="t1",
        source_uri="playbooks/t1/high-amount-review.json",
        source_hash_char="f",
        tags=("high-amount", "high-amount-playbook"),
        evidence_ids=("ev-high-amount",),
        body=(
            "1. Verify customer profile.\n"
            "2. Check recent velocity.\n\n"
            "See [High Amount Rule](/shared/rules/high-amount.md) and "
            "[KYC Checklist](/shared/references/kyc-checklist.md)."
        ),
    )
    _write_concept(
        t1_root,
        "playbooks/velocity-triage.md",
        concept_type="Investigation Playbook",
        title="Velocity Triage Playbook",
        description="Analyst steps for velocity spikes",
        tenant_scope="t1",
        source_uri="playbooks/t1/velocity-triage.json",
        source_hash_char="1",
        tags=("velocity-playbook",),
        body=(
            "Review anomalous activity patterns.\n\n"
            "Use [Velocity Spike Rule](/shared/rules/velocity-spike.md)."
        ),
    )

    t2_root = tenant_root / "t2"
    _write_index(t2_root, "# Tenant t2 bundle")
    _write_concept(
        t2_root,
        "playbooks/t2-secret.md",
        concept_type="Investigation Playbook",
        title="T2 Secret Playbook",
        description="Tenant t2 only guidance",
        tenant_scope="t2",
        source_uri="playbooks/t2/secret.json",
        source_hash_char="2",
        tags=("t2-secret",),
        body="Do not expose this playbook outside tenant t2.",
    )


def _parse_bundles(shared_root: Path, tenant_root: Path) -> tuple[object, dict[str, object]]:
    shared_validation = validate_bundle(shared_root, scope="shared", tenant_id=None)
    assert shared_validation.valid is True
    assert shared_validation.bundle is not None
    shared_bundle = shared_validation.bundle

    tenant_bundles: dict[str, object] = {}
    for tenant_id in ("t1", "t2"):
        validation = validate_bundle(
            tenant_root / tenant_id,
            scope="tenant",
            tenant_id=tenant_id,
            shared_bundle=shared_bundle,
        )
        assert validation.valid is True
        assert validation.bundle is not None
        tenant_bundles[tenant_id] = validation.bundle
    return shared_bundle, tenant_bundles


@pytest.fixture(autouse=True)
def isolated_rag_db(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTIGATION_DATA_DIR", str(tmp_path / "rag"))
    monkeypatch.setenv("KNOWLEDGE_TTL_SECONDS", "86400")
    reset_connection_for_tests()
    yield
    reset_connection_for_tests()


@pytest.fixture
def retrieval_context(tmp_path: Path) -> RetrievalContext:
    shared_root = tmp_path / "shared"
    tenant_root = tmp_path / "tenants"
    _build_okf_layout(shared_root, tenant_root)
    shared_bundle, tenant_bundles = _parse_bundles(shared_root, tenant_root)
    registry = OkfRegistry(shared_root=shared_root, tenant_root=tenant_root)
    assert registry.reload().activated is True

    index_okf_concepts_sync(shared_bundle, embeddings=None)
    for bundle in tenant_bundles.values():
        index_okf_concepts_sync(bundle, embeddings=None)

    return RetrievalContext(
        registry=registry,
        shared_root=shared_root,
        tenant_root=tenant_root,
        shared_bundle=shared_bundle,
        tenant_bundles=tenant_bundles,
    )


@pytest.fixture
def registry(retrieval_context: RetrievalContext) -> OkfRegistry:
    return retrieval_context.registry


@pytest.fixture
def retrieval_corpus() -> list[dict[str, object]]:
    payload = Path(__file__).resolve().parent.parent / "resources" / "okf_retrieval_corpus_v1.json"
    with payload.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def test_exact_and_graph_results_precede_rag(
    retrieval_context: RetrievalContext,
) -> None:
    rag_calls: list[dict[str, object]] = []

    def rag_search(**kwargs):
        rag_calls.append(kwargs)
        return {
            "hits": [
                {
                    "title": "Analyst memo",
                    "snippet": "Escalate when manual analyst context mentions high amount.",
                    "score": 0.41,
                    "knowledge_kind": "memo",
                    "authority": 10,
                }
            ],
            "retrieval_mode": "keyword",
        }

    result = retrieve_knowledge(
        registry=retrieval_context.registry,
        tenant_id="t1",
        analyst_id="analyst-1",
        query="high-amount",
        limit=4,
        rag_search=rag_search,
    )

    assert rag_calls == [
        {
            "tenant_id": "t1",
            "analyst_id": "analyst-1",
            "query": "high-amount",
            "limit": 1,
        }
    ]
    assert [item.concept_id for item in result.results[:4]] == [
        "playbooks/high-amount-review",
        "rules/high-amount",
        "references/kyc-checklist",
        None,
    ]
    assert [item.authority for item in result.results[:4]] == [
        "tenant_okf",
        "shared_okf",
        "shared_okf",
        "memo_rag",
    ]
    assert result.results[2].retrieval_path == (
        "playbooks/high-amount-review",
        "references/kyc-checklist",
    )
    assert result.abstain is False
    assert result.conflicts == ()
    assert result.retrieval_mode == "exact+expand+keyword"


def test_results_deduplicate_by_concept_and_hash(
    retrieval_context: RetrievalContext,
) -> None:
    shared_bundle = retrieval_context.shared_bundle
    fresh_hash = shared_bundle.concepts["rules/high-amount"].content_hash
    stale_hash = "9" * 64

    result = retrieve_knowledge(
        registry=retrieval_context.registry,
        tenant_id="t1",
        analyst_id="analyst-1",
        query="High Amount Rule",
        limit=5,
        rag_search=lambda **_: {
            "hits": [
                {
                    "title": "High Amount Rule",
                    "snippet": "Fresh duplicate from indexed OKF.",
                    "score": 0.87,
                    "knowledge_kind": "okf",
                    "concept_id": "rules/high-amount",
                    "bundle_scope": "shared",
                    "content_hash": fresh_hash,
                    "source_uri": "rules/default.json#high-amount",
                    "authority": 20,
                },
                {
                    "title": "High Amount Rule",
                    "snippet": "Second duplicate from indexed OKF.",
                    "score": 0.72,
                    "knowledge_kind": "okf",
                    "concept_id": "rules/high-amount",
                    "bundle_scope": "shared",
                    "content_hash": fresh_hash,
                    "source_uri": "rules/default.json#high-amount",
                    "authority": 20,
                },
                {
                    "title": "High Amount Rule",
                    "snippet": "Stale indexed row.",
                    "score": 0.99,
                    "knowledge_kind": "okf",
                    "concept_id": "rules/high-amount",
                    "bundle_scope": "shared",
                    "content_hash": stale_hash,
                    "source_uri": "rules/default.json#high-amount",
                    "authority": 20,
                },
                {
                    "title": "Analyst memo",
                    "snippet": "Duplicate memo one.",
                    "score": 0.51,
                    "knowledge_kind": "memo",
                    "content_hash": "memo-hash-1",
                    "authority": 10,
                },
                {
                    "title": "Analyst memo",
                    "snippet": "Duplicate memo two.",
                    "score": 0.49,
                    "knowledge_kind": "memo",
                    "content_hash": "memo-hash-1",
                    "authority": 10,
                },
            ],
            "retrieval_mode": "keyword",
        },
    )

    concept_results = [
        item for item in result.results if item.concept_id == "rules/high-amount"
    ]
    memo_results = [item for item in result.results if item.authority == "memo_rag"]
    assert len(concept_results) == 1
    assert concept_results[0].content_hash == fresh_hash
    assert all(item.content_hash != stale_hash for item in result.results)
    assert len(memo_results) == 1


def test_embedding_failure_uses_keyword_fallback(
    retrieval_context: RetrievalContext,
) -> None:
    result = retrieve_knowledge(
        registry=retrieval_context.registry,
        tenant_id="t1",
        analyst_id="analyst-1",
        query="legacy memo",
        limit=3,
        rag_search=lambda **_: {
            "hits": [
                {
                    "title": "Legacy memo",
                    "snippet": "Legacy memo about prior escalations.",
                    "score": 0.61,
                    "knowledge_kind": "memo",
                    "authority": 10,
                }
            ],
            "retrieval_mode": "keyword_fallback",
        },
    )

    assert result.retrieval_mode == "keyword_fallback"
    assert [item.authority for item in result.results] == ["memo_rag"]
    assert result.abstain is True


def test_equal_authority_conflict_requires_abstention(
    retrieval_context: RetrievalContext,
) -> None:
    result = retrieve_knowledge(
        registry=retrieval_context.registry,
        tenant_id="t1",
        analyst_id="analyst-1",
        query="Conflicting Guidance",
        limit=10,
        rag_search=lambda **_: {"hits": [], "retrieval_mode": "keyword"},
    )

    assert {item.concept_id for item in result.results} == {
        "guidance/conflict-a",
        "guidance/conflict-b",
    }
    assert result.abstain is True
    assert result.conflicts == (
        "shared_okf conflict for guidance/shared-conflict.json: "
        "guidance/conflict-a != guidance/conflict-b",
    )


def test_frozen_corpus_recall_at_10(
    registry: OkfRegistry, retrieval_corpus: list[dict[str, object]]
) -> None:
    resolved = 0
    expected = 0
    for row in retrieval_corpus:
        result = retrieve_knowledge(
            registry=registry,
            tenant_id=row["tenant_id"],
            analyst_id="corpus",
            query=row["query"],
            limit=10,
            rag_search=lambda **_: {"hits": [], "retrieval_mode": "keyword"},
        )
        actual = {item.concept_id for item in result.results if item.concept_id}
        wanted = set(row["expected_concept_ids"])
        resolved += len(actual & wanted)
        expected += len(wanted)
        if row["unsupported"]:
            assert result.abstain is True
    assert resolved / max(expected, 1) >= 0.95
