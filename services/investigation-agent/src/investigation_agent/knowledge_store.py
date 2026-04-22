from __future__ import annotations

from typing import Any

from investigation_agent.knowledge_db import (
    count_docs,
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

"""Facade: investigation memo RAG (SQLite + optional OpenAI embeddings)."""

__all__ = [
    "count_docs",
    "ingest_document",
    "ingest_document_async",
    "rag_db_path",
    "reset_rag_connection_for_tests",
    "search",
    "search_async",
    "ttl_seconds",
]


def ingest_document(tenant_id: str, analyst_id: str, title: str, body: str) -> str:
    """Sync ingest without embeddings (tests / fallback)."""
    return ingest_document_sync(tenant_id, analyst_id, title, body, embeddings=None, embedding_model=None)


def search(tenant_id: str, analyst_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Sync keyword-only search (tests / no HTTP)."""
    return search_keyword_only(tenant_id, analyst_id, query, limit)
