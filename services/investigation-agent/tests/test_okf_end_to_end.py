"""End-to-end OKF gates for activation, retrieval, fallback, and atomic index swap.

ponytail: admin/reload HTTP wiring and deploy packaging land in a later PR; this
suite exercises the same prepare→replace→activate + hybrid retrieval semantics
at the library boundary.
"""

from __future__ import annotations

import asyncio
import sqlite3
from typing import Any
from pathlib import Path

import pytest

from investigation_agent import knowledge_db
from investigation_agent import knowledge_store
from investigation_agent.citation_schema import build_standard_citations
from investigation_agent.config import settings
from investigation_agent.knowledge_db import (
    db_path,
    ingest_document_sync,
    reset_connection_for_tests,
    search_hybrid,
)
from investigation_agent.okf_registry import OkfRegistry
from investigation_agent.okf_retrieval import retrieve_knowledge, retrieve_knowledge_async
from tests.okf_provenance_helpers import (
    attach_concept_provenance,
    remove_concept_provenance,
)


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
    attach_concept_provenance(
        root,
        path,
        source_record={
            "fixture_concept_id": Path(rel_path).with_suffix("").as_posix(),
            "fixture_source_marker": source_hash_char,
        },
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


def _configure_okf_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    shared_root: Path,
    tenant_root: Path,
) -> None:
    monkeypatch.setattr(settings, "okf_enabled", True)
    monkeypatch.setattr(settings, "okf_shared_root", str(shared_root))
    monkeypatch.setattr(settings, "okf_tenant_root", str(tenant_root))
    monkeypatch.setattr(settings, "okf_max_link_depth", 2)
    monkeypatch.setattr(settings, "okf_max_concepts", 24)


async def _semantic_embeddings(*_: Any, texts: list[str], **__: Any) -> list[list[float]]:
    vectors: list[list[float]] = []
    for text in texts:
        lowered = text.casefold()
        if "fresh reload marker" in lowered:
            vectors.append([0.0, 1.0, 0.0])
        elif "account activity" in lowered or "confirm profile" in lowered:
            vectors.append([1.0, 0.0, 0.0])
        else:
            vectors.append([0.0, 0.0, 1.0])
    return vectors


async def _activate_with_index(
    registry: OkfRegistry,
    *,
    use_embeddings: bool = False,
    api_key: str = "",
) -> str:
    candidate = registry.prepare_reload()
    assert not candidate.issues
    rows, _indexed = await knowledge_store.prepare_okf_index_rows_async(
        None,
        candidate.bundles,
        use_embeddings=use_embeddings,
        api_key=api_key,
        base_url="http://embeddings.local/v1",
        embed_model="test-embedding",
    )
    knowledge_store.replace_okf_index_rows_sync(rows)
    result = registry.activate(candidate)
    assert result.activated is True
    return result.revision


def _hits_from_retrieval(result: Any) -> list[dict[str, Any]]:
    return [
        {
            "concept_id": item.concept_id,
            "authority": item.authority,
            "authority_label": item.authority,
            "evidence_ids": list(item.evidence_ids),
            "retrieval_path": list(item.retrieval_path),
            "text": item.text,
            "content_hash": item.content_hash,
            "score": item.score,
        }
        for item in result.results
    ]


@pytest.mark.asyncio
async def test_prepare_indexes_bundles_and_hybrid_retrieval_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_root = tmp_path / "shared"
    tenant_root = tmp_path / "tenants"
    _build_bundle_tree(shared_root, tenant_root)
    _configure_okf_settings(
        monkeypatch,
        shared_root=shared_root,
        tenant_root=tenant_root,
    )
    monkeypatch.setattr(knowledge_db.emb_mod, "embed_texts", _semantic_embeddings)

    registry = OkfRegistry(shared_root=shared_root, tenant_root=tenant_root)
    indexed_bundles: list[tuple[str, str | None]] = []
    real_preparer = knowledge_store.prepare_okf_index_rows_async

    async def spy_preparer(
        http: Any, bundles: tuple[Any, ...], **kwargs: Any
    ) -> tuple[tuple[Any, ...], int]:
        indexed_bundles.extend((bundle.scope, bundle.tenant_id) for bundle in bundles)
        return await real_preparer(http, bundles, **kwargs)

    monkeypatch.setattr(knowledge_store, "prepare_okf_index_rows_async", spy_preparer)
    await _activate_with_index(registry, use_embeddings=True, api_key="test-key")

    assert {scope for scope, _ in indexed_bundles} == {"shared", "tenant"}
    assert ("tenant", "t1") in indexed_bundles
    assert ("tenant", "t2") in indexed_bundles

    query_vec = (await _semantic_embeddings(texts=["account activity"]))[0]
    hybrid_hits = search_hybrid("t1", "analyst-1", "account activity", 3, query_vec)
    assert hybrid_hits[0]["concept_id"] == "references/kyc-checklist"
    assert hybrid_hits[0]["authority"] == knowledge_db._AUTHORITY_SHARED_OKF

    ingest_document_sync(
        "t1",
        "analyst-1",
        "Residual high amount memo",
        "Residual chargeback memo for high amount rule escalation and manual review.",
    )

    result = retrieve_knowledge(
        registry=registry,
        tenant_id="t1",
        analyst_id="analyst-1",
        query="High Amount Rule",
        limit=4,
        rag_search=lambda **kwargs: {
            "hits": search_hybrid(
                str(kwargs["tenant_id"]),
                str(kwargs["analyst_id"]),
                str(kwargs["query"]),
                int(kwargs["limit"]),
                None,
            ),
            "retrieval_mode": "keyword_fallback",
        },
    )
    hits = _hits_from_retrieval(result)
    assert result.retrieval_mode == "exact+expand+keyword_fallback"
    assert [hit["concept_id"] for hit in hits] == [
        "rules/high-amount",
        "playbooks/high-amount-review",
        "references/kyc-checklist",
        None,
    ]
    assert [hit["authority_label"] for hit in hits] == [
        "tenant_okf",
        "tenant_okf",
        "shared_okf",
        "memo_rag",
    ]
    assert hits[1]["retrieval_path"] == [
        "rules/high-amount",
        "playbooks/high-amount-review",
    ]

    claim_concepts = [hit["concept_id"] for hit in hits if hit["authority"] == "tenant_okf"]
    claim_evidence = [
        evidence_id
        for hit in hits
        if hit["authority"] == "tenant_okf"
        for evidence_id in hit["evidence_ids"]
    ]
    resolves_to = [{"artifact": "okf_concept", "id": cid} for cid in claim_concepts]
    resolves_to.extend({"artifact": "evidence", "id": eid} for eid in claim_evidence)
    citations, summary = build_standard_citations(
        claims=[
            {
                "text": "Use the high amount rule and linked playbook.",
                "source": "tool",
                "resolves_to": resolves_to,
            }
        ],
        deterministic_support=[{"claim_index": 0, "supported": True}],
    )
    resolved = {(item["artifact"], item["id"]) for item in citations[0]["resolves_to"]}
    assert summary.supported_count == 1
    assert ("okf_concept", "rules/high-amount") in resolved
    assert ("okf_concept", "playbooks/high-amount-review") in resolved
    assert ("evidence", "ev-rule") in resolved
    assert ("evidence", "ev-playbook") in resolved

    t2_result = retrieve_knowledge(
        registry=registry,
        tenant_id="t1",
        analyst_id="analyst-1",
        query="T2 Secret Playbook",
        limit=5,
        rag_search=lambda **_: {"hits": [], "retrieval_mode": "keyword"},
    )
    assert "playbooks/t2-secret" not in {
        item.concept_id for item in t2_result.results if item.concept_id
    }


@pytest.mark.asyncio
async def test_atomic_reload_refreshes_index_and_failed_reload_keeps_prior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_root = tmp_path / "shared"
    tenant_root = tmp_path / "tenants"
    _build_bundle_tree(shared_root, tenant_root)
    _configure_okf_settings(
        monkeypatch,
        shared_root=shared_root,
        tenant_root=tenant_root,
    )
    monkeypatch.setattr(knowledge_db.emb_mod, "embed_texts", _semantic_embeddings)
    registry = OkfRegistry(shared_root=shared_root, tenant_root=tenant_root)
    await _activate_with_index(registry, use_embeddings=True, api_key="test-key")

    indexed_after_reload: list[tuple[str, str | None]] = []
    real_preparer = knowledge_store.prepare_okf_index_rows_async

    async def spy_preparer(
        http: Any, bundles: tuple[Any, ...], **kwargs: Any
    ) -> tuple[tuple[Any, ...], int]:
        indexed_after_reload.extend((bundle.scope, bundle.tenant_id) for bundle in bundles)
        return await real_preparer(http, bundles, **kwargs)

    monkeypatch.setattr(knowledge_store, "prepare_okf_index_rows_async", spy_preparer)

    _write_concept(
        tenant_root / "t1",
        "playbooks/fresh-reload.md",
        concept_type="Investigation Playbook",
        title="Fresh Reload Playbook",
        tenant_scope="t1",
        source_uri="playbooks/t1/fresh-reload.json",
        source_hash_char="f",
        evidence_ids=("ev-reload",),
        body="Fresh reload marker guidance for newly approved overlays.",
    )
    await _activate_with_index(registry, use_embeddings=True, api_key="test-key")
    assert ("shared", None) in indexed_after_reload
    assert ("tenant", "t1") in indexed_after_reload

    query_vec = (await _semantic_embeddings(texts=["fresh reload marker"]))[0]
    refreshed = search_hybrid("t1", "analyst-1", "fresh reload marker", 3, query_vec)
    assert refreshed[0]["concept_id"] == "playbooks/fresh-reload"

    prior_tenant_revision = registry.snapshot_revision("t1")
    indexed_after_reload.clear()
    (shared_root / "rules" / "high-amount.md").write_text("invalid\n", encoding="utf-8")
    failed = registry.prepare_reload()
    assert failed.issues
    assert registry.snapshot_revision("t1") == prior_tenant_revision
    assert indexed_after_reload == []
    still_searchable = search_hybrid("t1", "analyst-1", "fresh reload marker", 3, query_vec)
    assert still_searchable[0]["concept_id"] == "playbooks/fresh-reload"


@pytest.mark.asyncio
async def test_atomic_reload_purges_removed_okf_concepts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_root = tmp_path / "shared"
    tenant_root = tmp_path / "tenants"
    _build_bundle_tree(shared_root, tenant_root)
    _configure_okf_settings(
        monkeypatch,
        shared_root=shared_root,
        tenant_root=tenant_root,
    )
    monkeypatch.setattr(knowledge_db.emb_mod, "embed_texts", _semantic_embeddings)
    registry = OkfRegistry(shared_root=shared_root, tenant_root=tenant_root)
    await _activate_with_index(registry, use_embeddings=True, api_key="test-key")

    concept_path = tenant_root / "t1" / "playbooks" / "fresh-reload.md"
    _write_concept(
        tenant_root / "t1",
        "playbooks/fresh-reload.md",
        concept_type="Investigation Playbook",
        title="Fresh Reload Playbook",
        tenant_scope="t1",
        source_uri="playbooks/t1/fresh-reload.json",
        source_hash_char="f",
        evidence_ids=("ev-reload",),
        body="Fresh reload marker guidance for newly approved overlays.",
    )
    await _activate_with_index(registry, use_embeddings=True, api_key="test-key")
    query_vec = (await _semantic_embeddings(texts=["fresh reload marker"]))[0]
    assert (
        search_hybrid("t1", "analyst-1", "fresh reload marker", 3, query_vec)[0]["concept_id"]
        == "playbooks/fresh-reload"
    )

    concept_path.unlink()
    remove_concept_provenance(
        tenant_root / "t1",
        "playbooks/t1/fresh-reload.json",
    )
    await _activate_with_index(registry, use_embeddings=True, api_key="test-key")
    after_purge = search_hybrid("t1", "analyst-1", "fresh reload marker", 5, query_vec)
    assert "playbooks/fresh-reload" not in {hit.get("concept_id") for hit in after_purge}
    row = (
        sqlite3.connect(db_path())
        .execute(
            """
            SELECT COUNT(*) FROM knowledge_chunks
            WHERE knowledge_kind = 'okf' AND concept_id = 'playbooks/fresh-reload'
            """
        )
        .fetchone()
    )
    assert row[0] == 0


@pytest.mark.asyncio
async def test_mid_index_failure_rolls_back_search_index_and_keeps_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_root = tmp_path / "shared"
    tenant_root = tmp_path / "tenants"
    _build_bundle_tree(shared_root, tenant_root)
    _configure_okf_settings(
        monkeypatch,
        shared_root=shared_root,
        tenant_root=tenant_root,
    )
    monkeypatch.setattr(knowledge_db.emb_mod, "embed_texts", _semantic_embeddings)
    registry = OkfRegistry(shared_root=shared_root, tenant_root=tenant_root)
    await _activate_with_index(registry, use_embeddings=True, api_key="test-key")
    prior_tenant_revision = registry.snapshot_revision("t1")
    query_vec = (await _semantic_embeddings(texts=["account activity"]))[0]
    prior_hit = search_hybrid("t1", "analyst-1", "account activity", 3, query_vec)
    assert prior_hit[0]["concept_id"] == "references/kyc-checklist"

    _write_concept(
        tenant_root / "t1",
        "playbooks/mid-failure.md",
        concept_type="Investigation Playbook",
        title="Mid Failure Playbook",
        tenant_scope="t1",
        source_uri="playbooks/t1/mid-failure.json",
        source_hash_char="9",
        evidence_ids=("ev-mid-failure",),
        body="Mid failure marker guidance for injected rollback.",
    )
    candidate = registry.prepare_reload()
    assert not candidate.issues
    rows, _indexed = await knowledge_store.prepare_okf_index_rows_async(
        None,
        candidate.bundles,
        use_embeddings=True,
        api_key="test-key",
        base_url="http://embeddings.local/v1",
        embed_model="test-embedding",
    )
    original_insert = knowledge_db._insert_okf_index_row
    inserted = 0

    def fail_after_first_insert(*args: Any, **kwargs: Any) -> None:
        nonlocal inserted
        inserted += 1
        original_insert(*args, **kwargs)
        if inserted == 1:
            raise RuntimeError("injected mid-index failure")

    monkeypatch.setattr(knowledge_db, "_insert_okf_index_row", fail_after_first_insert)
    with pytest.raises(RuntimeError, match="injected mid-index failure"):
        knowledge_store.replace_okf_index_rows_sync(rows)

    # Registry must not activate when index replace fails.
    assert registry.snapshot_revision("t1") == prior_tenant_revision
    still_prior = search_hybrid("t1", "analyst-1", "account activity", 3, query_vec)
    assert still_prior[0]["concept_id"] == "references/kyc-checklist"
    not_visible = search_hybrid("t1", "analyst-1", "mid failure marker", 5, query_vec)
    assert "playbooks/mid-failure" not in {hit.get("concept_id") for hit in not_visible}


@pytest.mark.asyncio
async def test_async_retrieval_holds_generation_gate_until_rag_completes(
    tmp_path: Path,
) -> None:
    shared_root = tmp_path / "shared"
    tenant_root = tmp_path / "tenants"
    _build_bundle_tree(shared_root, tenant_root)
    registry = OkfRegistry(shared_root=shared_root, tenant_root=tenant_root)
    assert registry.reload().activated is True

    gate = asyncio.Lock()
    rag_started = asyncio.Event()
    allow_rag_finish = asyncio.Event()
    reload_entered = asyncio.Event()

    async def rag_search(**_kwargs: Any) -> dict[str, Any]:
        rag_started.set()
        await allow_rag_finish.wait()
        return {
            "hits": [
                {
                    "title": "Analyst memo",
                    "snippet": "Memo filler for high amount review.",
                    "score": 0.25,
                    "knowledge_kind": "memo",
                    "authority": 10,
                }
            ],
            "retrieval_mode": "keyword",
        }

    retrieval_task = asyncio.create_task(
        retrieve_knowledge_async(
            registry=registry,
            tenant_id="t1",
            analyst_id="analyst-1",
            query="High Amount Rule",
            limit=4,
            rag_search=rag_search,
            generation_gate=gate,
        )
    )
    await rag_started.wait()

    async def reload_attempt() -> None:
        async with gate:
            reload_entered.set()

    reload_task = asyncio.create_task(reload_attempt())
    await asyncio.sleep(0)
    assert reload_entered.is_set() is False

    allow_rag_finish.set()
    result = await retrieval_task
    await reload_task

    assert reload_entered.is_set() is True
    assert result.bundle_revision == registry.snapshot_revision("t1")
    returned = {
        item.concept_id: item.content_hash for item in result.results if item.concept_id is not None
    }
    active = {
        hit.concept.concept_id: hit.concept.content_hash
        for hit in registry.expand(
            "t1",
            ("rules/high-amount",),
            max_depth=2,
            max_concepts=4,
        )
    }
    assert returned.items() <= active.items()


@pytest.mark.asyncio
async def test_concurrent_reloads_serialize_candidate_preparation_through_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_root = tmp_path / "shared"
    tenant_root = tmp_path / "tenants"
    _build_bundle_tree(shared_root, tenant_root)
    _configure_okf_settings(
        monkeypatch,
        shared_root=shared_root,
        tenant_root=tenant_root,
    )
    registry = OkfRegistry(shared_root=shared_root, tenant_root=tenant_root)
    first_entered = asyncio.Event()
    first_can_finish = asyncio.Event()
    second_prepared = asyncio.Event()
    gate = asyncio.Lock()

    async def reload_once(label: str) -> str:
        async with gate:
            candidate = registry.prepare_reload()
            assert not candidate.issues
            if label == "first":
                first_entered.set()
                await first_can_finish.wait()
            else:
                second_prepared.set()
            rows, _indexed = await knowledge_store.prepare_okf_index_rows_async(
                None,
                candidate.bundles,
                use_embeddings=False,
                api_key="",
                base_url="",
                embed_model="",
            )
            knowledge_store.replace_okf_index_rows_sync(rows)
            result = registry.activate(candidate)
            return result.revision

    first_task = asyncio.create_task(reload_once("first"))
    await first_entered.wait()
    _write_concept(
        tenant_root / "t1",
        "playbooks/newer-reload.md",
        concept_type="Investigation Playbook",
        title="Newer Reload Playbook",
        tenant_scope="t1",
        source_uri="playbooks/t1/newer-reload.json",
        source_hash_char="d",
        evidence_ids=("ev-newer",),
        body="Newer reload marker.",
    )
    second_task = asyncio.create_task(reload_once("second"))
    await asyncio.sleep(0)
    assert second_prepared.is_set() is False

    first_can_finish.set()
    first_revision = await first_task
    second_revision = await second_task

    assert first_revision != second_revision
    assert registry.resolve("t1", "Newer Reload Playbook")[0].concept.concept_id == (
        "playbooks/newer-reload"
    )
