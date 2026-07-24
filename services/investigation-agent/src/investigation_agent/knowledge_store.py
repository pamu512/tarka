from __future__ import annotations

from typing import Any

from investigation_agent.knowledge_db import (
    count_docs,
    health_check as rag_health_check,
    index_okf_bundle_async,
    index_okf_concepts_sync,
    ingest_document_async,
    ingest_document_sync,
    search_async,
    search_keyword_only,
    ttl_seconds,
)
from investigation_agent.knowledge_db import (
    db_path as rag_db_path,
)
from investigation_agent.knowledge_db import (
    reset_connection_for_tests as reset_rag_connection_for_tests,
)
from investigation_agent.okf_registry import OkfRegistry
from investigation_agent.okf_retrieval import (
    KnowledgeResult,
    KnowledgeRetrievalResult,
    retrieve_knowledge,
    retrieve_knowledge_async as _retrieve_knowledge_async,
)

"""Facade: investigation memo RAG (SQLite + optional OpenAI embeddings)."""

__all__ = [
    "KnowledgeResult",
    "KnowledgeRetrievalResult",
    "count_docs",
    "index_okf_bundle_async",
    "index_okf_concepts_sync",
    "ingest_document",
    "ingest_document_async",
    "rag_db_path",
    "rag_health_check",
    "reset_rag_connection_for_tests",
    "retrieve_knowledge",
    "retrieve_knowledge_async",
    "search",
    "search_async",
    "ttl_seconds",
]


def ingest_document(tenant_id: str, analyst_id: str, title: str, body: str) -> str:
    """Sync ingest without embeddings (tests / fallback)."""
    return ingest_document_sync(
        tenant_id, analyst_id, title, body, embeddings=None, embedding_model=None
    )


def search(tenant_id: str, analyst_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Sync keyword-only search (tests / no HTTP)."""
    return search_keyword_only(tenant_id, analyst_id, query, limit)


async def retrieve_knowledge_async(
    http: Any,
    *,
    registry: OkfRegistry,
    use_embeddings: bool,
    api_key: str,
    base_url: str,
    embed_model: str,
    tenant_id: str,
    analyst_id: str,
    query: str,
    limit: int = 5,
    keyword_weight: float = 0.35,
) -> KnowledgeRetrievalResult:
    return await _retrieve_knowledge_async(
        registry=registry,
        tenant_id=tenant_id,
        analyst_id=analyst_id,
        query=query,
        limit=limit,
        rag_search=lambda **kwargs: search_async(
            http,
            use_embeddings=use_embeddings,
            api_key=api_key,
            base_url=base_url,
            embed_model=embed_model,
            tenant_id=str(kwargs["tenant_id"]),
            analyst_id=str(kwargs["analyst_id"]),
            query=str(kwargs["query"]),
            limit=int(kwargs["limit"]),
            keyword_weight=keyword_weight,
        ),
    )
