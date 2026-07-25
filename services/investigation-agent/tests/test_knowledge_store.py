from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest
from investigation_agent import knowledge_store
from investigation_agent.knowledge_db import (
    db_path,
    reset_connection_for_tests,
)
from investigation_agent.knowledge_store import index_okf_concepts_sync
from investigation_agent.okf_models import OkfConcept, ParsedBundle


def _concept(
    concept_id: str,
    *,
    scope: str,
    tenant_scope: str | None = None,
    title: str,
    description: str = "",
    tags: tuple[str, ...] = (),
    body: str = "",
    content_hash: str | None = None,
) -> OkfConcept:
    raw_hash = content_hash or f"{concept_id}-hash-{'a' * 56}"
    return OkfConcept(
        concept_id=concept_id,
        path=Path(f"/virtual/{concept_id}.md"),
        concept_type="Fraud Rule",
        title=title,
        description=description,
        tags=tags,
        timestamp=None,
        source_uri=f"docs/{concept_id}",
        source_content_hash="b" * 64,
        approval_status="approved",
        approved_revision="rev-1",
        sensitivity="internal",
        tenant_scope=tenant_scope if tenant_scope is not None else scope,
        evidence_ids=(),
        body=body,
        links=(),
        content_hash=raw_hash,
        frontmatter={},
    )


@pytest.fixture
def shared_bundle() -> ParsedBundle:
    return ParsedBundle(
        root=Path("/virtual/shared"),
        scope="shared",
        tenant_id=None,
        revision="rev-shared",
        concepts={
            "rules/high-amount": _concept(
                "rules/high-amount",
                scope="shared",
                title="High Amount Rule",
                description="Flags high amount transactions",
                tags=("high-amount",),
                body="Transactions above threshold need review.",
            ),
        },
    )


@pytest.fixture
def t1_bundle() -> ParsedBundle:
    return ParsedBundle(
        root=Path("/virtual/t1"),
        scope="t1",
        tenant_id="t1",
        revision="rev-t1",
        concepts={
            "playbooks/t1-review": _concept(
                "playbooks/t1-review",
                scope="t1",
                tenant_scope="t1",
                title="T1 Review Playbook",
                description="Steps for t1 high amount",
                tags=("high-amount", "playbook"),
                body="Verify customer profile for t1.",
            ),
        },
    )


@pytest.fixture
def t2_bundle() -> ParsedBundle:
    return ParsedBundle(
        root=Path("/virtual/t2"),
        scope="t2",
        tenant_id="t2",
        revision="rev-t2",
        concepts={
            "playbooks/t2-secret": _concept(
                "playbooks/t2-secret",
                scope="t2",
                tenant_scope="t2",
                title="T2 Secret Playbook",
                description="t2 only secret steps",
                tags=("secret",),
                body="t2 secret handling procedure.",
            ),
        },
    )


@pytest.fixture(autouse=True)
def isolated_rag_db(tmp_path, monkeypatch):
    monkeypatch.setenv("INVESTIGATION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("KNOWLEDGE_TTL_SECONDS", "86400")
    reset_connection_for_tests()
    yield
    reset_connection_for_tests()


def test_ingest_and_search():
    doc_id = knowledge_store.ingest_document(
        "t1", "a1", "Runbook", "refund abuse patterns\n\nVPN velocity"
    )
    assert doc_id
    hits = knowledge_store.search("t1", "a1", "refund VPN", limit=3)
    assert len(hits) >= 1
    assert hits[0]["doc_id"] == doc_id


def test_search_other_scope_empty():
    knowledge_store.ingest_document("t2", "a2", "x", "secret memo alpha")
    assert knowledge_store.search("t1", "a1", "secret memo") == []


def test_count_docs():
    knowledge_store.ingest_document("t3", "a3", "one", "hello")
    assert knowledge_store.count_docs("t3", "a3") >= 1


def test_search_sees_shared_and_own_tenant_okf_but_not_other_tenant(
    shared_bundle, t1_bundle, t2_bundle
):
    index_okf_concepts_sync(shared_bundle, embeddings=None)
    index_okf_concepts_sync(t1_bundle, embeddings=None)
    index_okf_concepts_sync(t2_bundle, embeddings=None)
    hits = knowledge_store.search("t1", "a1", "high amount", limit=20)
    ids = {h.get("concept_id") for h in hits}
    assert "rules/high-amount" in ids
    assert "playbooks/t1-review" in ids
    assert "playbooks/t2-secret" not in ids


def test_existing_schema_migrates_without_data_loss(tmp_path, monkeypatch):
    path = tmp_path / "legacy.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE knowledge_chunks (
            chunk_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            analyst_id TEXT NOT NULL,
            doc_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            title TEXT NOT NULL,
            text TEXT NOT NULL,
            embedding_json TEXT,
            embedding_model TEXT,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO knowledge_chunks
        (chunk_id, tenant_id, analyst_id, doc_id, chunk_index, title, text,
         embedding_json, embedding_model, created_at)
        VALUES ('c1', 't1', 'a1', 'd1', 0, 'Legacy', 'legacy memo text', NULL, NULL, ?)
        """,
        (time.time(),),
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("INVESTIGATION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COPILOT_RAG_DB_NAME", "legacy.sqlite3")
    reset_connection_for_tests()

    hits = knowledge_store.search("t1", "a1", "legacy memo", limit=5)
    assert len(hits) >= 1
    assert hits[0]["title"] == "Legacy"
    assert hits[0].get("knowledge_kind") == "memo"


def test_okf_rows_survive_memo_ttl_pruning(shared_bundle, monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_TTL_SECONDS", "60")
    reset_connection_for_tests()

    index_okf_concepts_sync(shared_bundle, embeddings=None)
    knowledge_store.ingest_document("t1", "a1", "Fresh", "fresh analyst memo")

    conn = sqlite3.connect(db_path())
    conn.execute(
        "UPDATE knowledge_chunks SET created_at = ? WHERE knowledge_kind = 'memo'",
        (time.time() - 120,),
    )
    conn.commit()
    conn.close()
    reset_connection_for_tests()

    knowledge_store.ingest_document("t1", "a1", "Trigger prune", "new memo triggers ttl prune")
    hits = knowledge_store.search("t1", "a1", "high amount threshold", limit=20)
    ids = {h.get("concept_id") for h in hits}
    assert "rules/high-amount" in ids
