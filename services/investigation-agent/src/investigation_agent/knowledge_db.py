from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import uuid
from typing import Any

from investigation_agent import embeddings as emb_mod
from investigation_agent.okf_models import OkfConcept, ParsedBundle

"""
SQLite-backed investigation memos with optional embedding vectors (RAG).
Hybrid retrieval: cosine similarity + keyword overlap when embeddings exist.
"""
_OKF_ANALYST_ID = "__okf__"
_SHARED_TENANT_ID = "__shared__"
_OKF_KIND = "okf"
_MEMO_KIND = "memo"
_AUTHORITY_MEMO = 10
_AUTHORITY_SHARED_OKF = 20
_AUTHORITY_TENANT_OKF = 30
_MAX_DOCS_PER_SCOPE = 80
_MAX_DOC_CHARS = 120_000
_MAX_CHUNK = 1800
_DEFAULT_TTL = 2 * 3600
_MAX_CHUNKS_SCAN = 2500
_KEYWORD_MAX_TOKENS = 24

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def ttl_seconds() -> int:
    try:
        v = int(os.environ.get("KNOWLEDGE_TTL_SECONDS", str(_DEFAULT_TTL)))
        return max(300, min(v, 86400))
    except ValueError:
        return _DEFAULT_TTL


def _data_dir() -> str:
    d = os.environ.get("INVESTIGATION_DATA_DIR", "").strip()
    if not d:
        d = os.path.join(os.getcwd(), "var", "investigation-agent")
    os.makedirs(d, exist_ok=True)
    return d


def db_path() -> str:
    name = (
        os.environ.get("COPILOT_RAG_DB_NAME", "knowledge_rag.sqlite3").strip()
        or "knowledge_rag.sqlite3"
    )
    return os.path.join(_data_dir(), name)


def _get_conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            path = db_path()
            _conn = sqlite3.connect(path, check_same_thread=False)
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.execute("PRAGMA synchronous=NORMAL")
            _init_schema(_conn)
        return _conn


def _init_schema(c: sqlite3.Connection) -> None:
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_chunks (
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
    _migrate_schema(c)
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_scope ON knowledge_chunks (tenant_id, analyst_id, created_at)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_doc ON knowledge_chunks (tenant_id, analyst_id, doc_id)"
    )
    c.commit()


def _migrate_schema(c: sqlite3.Connection) -> None:
    cols = {row[1] for row in c.execute("PRAGMA table_info(knowledge_chunks)")}
    additions = [
        ("knowledge_kind", "TEXT NOT NULL DEFAULT 'memo'"),
        ("concept_id", "TEXT"),
        ("bundle_scope", "TEXT"),
        ("content_hash", "TEXT"),
        ("source_uri", "TEXT"),
        ("authority", "INTEGER NOT NULL DEFAULT 10"),
    ]
    for name, typedef in additions:
        if name not in cols:
            c.execute(f"ALTER TABLE knowledge_chunks ADD COLUMN {name} {typedef}")
    c.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_okf_concept
        ON knowledge_chunks (tenant_id, knowledge_kind, concept_id, chunk_index)
        """
    )


def reset_connection_for_tests() -> None:
    """Close singleton (tests only)."""
    global _conn
    with _lock:
        if _conn:
            _conn.close()
            _conn = None


def health_check() -> tuple[bool, str]:
    """Open the RAG SQLite database and execute a minimal query."""
    try:
        conn = _get_conn()
        conn.execute("SELECT 1").fetchone()
        return True, "ok"
    except Exception as exc:
        return False, f"{exc.__class__.__name__}: {str(exc)[:200]}"


def _chunk_text(text: str) -> list[str]:
    t = text.strip()
    if not t:
        return []
    if len(t) <= _MAX_CHUNK:
        return [t]
    parts = re.split(r"\n\n+", t)
    chunks: list[str] = []
    cur = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(cur) + len(p) + 2 <= _MAX_CHUNK:
            cur = f"{cur}\n\n{p}" if cur else p
        else:
            if cur:
                chunks.append(cur)
            if len(p) > _MAX_CHUNK:
                for i in range(0, len(p), _MAX_CHUNK):
                    chunks.append(p[i : i + _MAX_CHUNK])
                cur = ""
            else:
                cur = p
    if cur:
        chunks.append(cur)
    return chunks[:200]


def _keyword_score(text: str, query: str) -> float:
    low = text.lower()
    q_tokens = [t for t in re.split(r"\W+", query.lower()) if len(t) >= 2][:_KEYWORD_MAX_TOKENS]
    if not q_tokens:
        return 0.0
    return float(sum(1 for tok in q_tokens if tok in low))


def _trim_docs(c: sqlite3.Connection, tenant_id: str, analyst_id: str) -> None:
    rows = c.execute(
        """
        SELECT doc_id, MIN(created_at) AS t
        FROM knowledge_chunks
        WHERE tenant_id = ? AND analyst_id = ? AND knowledge_kind = ?
        GROUP BY doc_id
        ORDER BY t ASC
        """,
        (tenant_id, analyst_id, _MEMO_KIND),
    ).fetchall()
    if len(rows) <= _MAX_DOCS_PER_SCOPE:
        return
    drop = [r[0] for r in rows[: max(0, len(rows) - _MAX_DOCS_PER_SCOPE)]]
    for did in drop:
        c.execute(
            """
            DELETE FROM knowledge_chunks
            WHERE tenant_id = ? AND analyst_id = ? AND doc_id = ? AND knowledge_kind = ?
            """,
            (tenant_id, analyst_id, did, _MEMO_KIND),
        )


def _prune_expired(c: sqlite3.Connection, tenant_id: str, analyst_id: str, cutoff: float) -> None:
    c.execute(
        """
        DELETE FROM knowledge_chunks
        WHERE tenant_id = ? AND analyst_id = ? AND knowledge_kind = ? AND created_at < ?
        """,
        (tenant_id, analyst_id, _MEMO_KIND, cutoff),
    )


def ingest_document_sync(
    tenant_id: str,
    analyst_id: str,
    title: str,
    body: str,
    *,
    embeddings: list[list[float]] | None = None,
    embedding_model: str | None = None,
) -> str:
    """Persist chunks; embeddings optional (must align with chunk count if provided)."""
    title = (title or "untitled").strip()[:256]
    body = (body or "").strip()
    if not body:
        raise ValueError("body required")
    if len(body) > _MAX_DOC_CHARS:
        raise ValueError(f"body exceeds {_MAX_DOC_CHARS} characters")
    chunks = _chunk_text(body)
    if not chunks:
        raise ValueError("no ingestible text after trim")
    return ingest_chunks_sync(
        tenant_id,
        analyst_id,
        title,
        chunks,
        embeddings=embeddings,
        embedding_model=embedding_model,
    )


def ingest_chunks_sync(
    tenant_id: str,
    analyst_id: str,
    title: str,
    chunks: list[str],
    *,
    embeddings: list[list[float]] | None = None,
    embedding_model: str | None = None,
) -> str:
    title = (title or "untitled").strip()[:256]
    if embeddings is not None and len(embeddings) != len(chunks):
        raise ValueError("embeddings length must match chunk count")
    doc_id = str(uuid.uuid4())
    now = time.time()
    cutoff = now - ttl_seconds()
    c = _get_conn()
    with _lock:
        _prune_expired(c, tenant_id, analyst_id, cutoff)
        for i, ch in enumerate(chunks):
            cid = str(uuid.uuid4())
            ej = None
            if embeddings is not None:
                ej = json.dumps(embeddings[i])
            c.execute(
                """
                INSERT INTO knowledge_chunks
                (chunk_id, tenant_id, analyst_id, doc_id, chunk_index, title, text,
                 embedding_json, embedding_model, created_at, knowledge_kind, authority)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cid,
                    tenant_id,
                    analyst_id,
                    doc_id,
                    i,
                    title,
                    ch,
                    ej,
                    embedding_model,
                    now,
                    _MEMO_KIND,
                    _AUTHORITY_MEMO,
                ),
            )
        _trim_docs(c, tenant_id, analyst_id)
        c.commit()
    return doc_id


async def ingest_document_async(
    http: Any,
    *,
    use_embeddings: bool,
    api_key: str,
    base_url: str,
    embed_model: str,
    tenant_id: str,
    analyst_id: str,
    title: str,
    body: str,
) -> str:
    title = (title or "untitled").strip()[:256]
    body = (body or "").strip()
    if not body:
        raise ValueError("body required")
    if len(body) > _MAX_DOC_CHARS:
        raise ValueError(f"body exceeds {_MAX_DOC_CHARS} characters")
    chunks = _chunk_text(body)
    if not chunks:
        raise ValueError("no ingestible text after trim")
    vecs: list[list[float]] | None = None
    model: str | None = None
    if use_embeddings and api_key:
        try:
            vecs = await emb_mod.embed_texts(
                http,
                api_key=api_key,
                base_url=base_url,
                model=embed_model,
                texts=chunks,
            )
            model = embed_model
        except Exception:
            vecs = None
            model = None
    return ingest_chunks_sync(
        tenant_id,
        analyst_id,
        title,
        chunks,
        embeddings=vecs,
        embedding_model=model,
    )


def count_docs(tenant_id: str, analyst_id: str) -> int:
    c = _get_conn()
    now = time.time()
    cutoff = now - ttl_seconds()
    row = c.execute(
        """
        SELECT COUNT(DISTINCT doc_id) FROM knowledge_chunks
        WHERE tenant_id = ? AND analyst_id = ? AND knowledge_kind = ? AND created_at >= ?
        """,
        (tenant_id, analyst_id, _MEMO_KIND, cutoff),
    ).fetchone()
    return int(row[0] or 0) if row else 0


def search_keyword_only(
    tenant_id: str, analyst_id: str, query: str, limit: int = 5
) -> list[dict[str, Any]]:
    return _search_hybrid(tenant_id, analyst_id, query, limit, query_embedding=None)


def search_hybrid(
    tenant_id: str,
    analyst_id: str,
    query: str,
    limit: int,
    query_embedding: list[float] | None,
    *,
    hybrid_keyword_weight: float = 0.35,
) -> list[dict[str, Any]]:
    return _search_hybrid(
        tenant_id, analyst_id, query, limit, query_embedding, hybrid_keyword_weight
    )


def _search_hybrid(
    tenant_id: str,
    analyst_id: str,
    query: str,
    limit: int,
    query_embedding: list[float] | None,
    hybrid_keyword_weight: float = 0.35,
) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if not q or len(q) > 512:
        return []
    now = time.time()
    cutoff = now - ttl_seconds()
    c = _get_conn()
    rows = c.execute(
        """
        SELECT doc_id, chunk_index, title, text, embedding_json,
               knowledge_kind, concept_id, bundle_scope, content_hash, source_uri, authority
        FROM knowledge_chunks
        WHERE (
          (tenant_id = ? AND analyst_id = ? AND knowledge_kind = ? AND created_at >= ?)
          OR (tenant_id = ? AND analyst_id = ? AND knowledge_kind = ?)
          OR (tenant_id = ? AND analyst_id = ? AND knowledge_kind = ?)
        )
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (
            tenant_id,
            analyst_id,
            _MEMO_KIND,
            cutoff,
            tenant_id,
            _OKF_ANALYST_ID,
            _OKF_KIND,
            _SHARED_TENANT_ID,
            _OKF_ANALYST_ID,
            _OKF_KIND,
            _MAX_CHUNKS_SCAN,
        ),
    ).fetchall()
    scored: list[tuple[float, dict[str, Any]]] = []
    for (
        doc_id,
        chunk_index,
        title,
        text,
        ej,
        knowledge_kind,
        concept_id,
        bundle_scope,
        content_hash,
        source_uri,
        authority,
    ) in rows:
        kw = _keyword_score(text, q)
        sem = 0.0
        if query_embedding and ej:
            try:
                vec = json.loads(ej)
                if isinstance(vec, list) and vec and all(isinstance(x, (int, float)) for x in vec):
                    sem = max(0.0, emb_mod.cosine_sim(query_embedding, [float(x) for x in vec]))
            except (json.JSONDecodeError, TypeError):
                sem = 0.0
        if query_embedding and ej:
            combined = (1.0 - hybrid_keyword_weight) * sem + hybrid_keyword_weight * min(
                1.0, kw / 5.0
            )
        else:
            combined = kw
        if combined <= 0:
            continue
        snippet = text[:400] + ("…" if len(text) > 400 else "")
        scored.append(
            (
                combined,
                {
                    "doc_id": doc_id,
                    "title": title or "",
                    "chunk_index": int(chunk_index),
                    "snippet": snippet,
                    "score": round(combined, 4),
                    "semantic_score": round(sem, 4) if sem else None,
                    "keyword_hits": int(kw) if kw else None,
                    "knowledge_kind": knowledge_kind or _MEMO_KIND,
                    "concept_id": concept_id,
                    "bundle_scope": bundle_scope,
                    "content_hash": content_hash,
                    "source_uri": source_uri,
                    "authority": int(authority) if authority is not None else _AUTHORITY_MEMO,
                },
            ),
        )
    scored.sort(key=lambda x: -x[0])
    lim = max(1, min(limit, 15))
    return [x[1] for x in scored[:lim]]


async def search_async(
    http: Any,
    *,
    use_embeddings: bool,
    api_key: str,
    base_url: str,
    embed_model: str,
    tenant_id: str,
    analyst_id: str,
    query: str,
    limit: int = 5,
    keyword_weight: float = 0.35,
) -> dict[str, Any]:
    qvec: list[float] | None = None
    mode = "keyword"
    if use_embeddings and api_key and (query or "").strip():
        try:
            vecs = await emb_mod.embed_texts(
                http,
                api_key=api_key,
                base_url=base_url,
                model=embed_model,
                texts=[query.strip()[:8000]],
            )
            if vecs:
                qvec = vecs[0]
                mode = "hybrid" if qvec else "keyword"
        except Exception:
            qvec = None
            mode = "keyword_fallback"
    hits = search_hybrid(
        tenant_id,
        analyst_id,
        query,
        limit,
        qvec,
        hybrid_keyword_weight=keyword_weight,
    )
    return {"hits": hits, "query": query.strip()[:512], "retrieval_mode": mode}


def _okf_tenant_for_bundle(bundle: ParsedBundle) -> tuple[str, int]:
    if bundle.scope == "shared":
        return _SHARED_TENANT_ID, _AUTHORITY_SHARED_OKF
    tenant_id = (bundle.tenant_id or bundle.scope or "").strip()
    if not tenant_id:
        raise ValueError("tenant bundle requires tenant_id")
    return tenant_id, _AUTHORITY_TENANT_OKF


def _okf_index_text(concept: OkfConcept) -> str:
    parts = [concept.title]
    if concept.description:
        parts.append(concept.description)
    if concept.tags:
        parts.append("Tags: " + ", ".join(concept.tags))
    if concept.body:
        parts.append(concept.body)
    return "\n\n".join(parts)


def index_okf_concepts_sync(
    bundle: ParsedBundle,
    *,
    embeddings: list[list[float]] | None = None,
    embedding_model: str | None = None,
) -> int:
    """Index approved concepts from a parsed bundle; returns count of concepts indexed."""
    tenant_id, authority = _okf_tenant_for_bundle(bundle)
    analyst_id = _OKF_ANALYST_ID
    bundle_scope = bundle.scope
    indexed = 0
    now = time.time()
    c = _get_conn()
    with _lock:
        for concept_id, concept in bundle.concepts.items():
            if concept.approval_status != "approved":
                continue
            row = c.execute(
                """
                SELECT content_hash FROM knowledge_chunks
                WHERE tenant_id = ? AND analyst_id = ? AND knowledge_kind = ? AND concept_id = ?
                LIMIT 1
                """,
                (tenant_id, analyst_id, _OKF_KIND, concept_id),
            ).fetchone()
            if row and row[0] == concept.content_hash:
                continue
            c.execute(
                """
                DELETE FROM knowledge_chunks
                WHERE tenant_id = ? AND analyst_id = ? AND knowledge_kind = ? AND concept_id = ?
                """,
                (tenant_id, analyst_id, _OKF_KIND, concept_id),
            )
            text = _okf_index_text(concept)
            chunks = _chunk_text(text) or [concept.title]
            if embeddings is not None and len(embeddings) != len(chunks):
                raise ValueError("embeddings length must match chunk count")
            for i, ch in enumerate(chunks):
                cid = f"okf:{tenant_id}:{concept_id}:{i}"
                ej = json.dumps(embeddings[i]) if embeddings is not None else None
                c.execute(
                    """
                    INSERT INTO knowledge_chunks
                    (chunk_id, tenant_id, analyst_id, doc_id, chunk_index, title, text,
                     embedding_json, embedding_model, created_at, knowledge_kind, concept_id,
                     bundle_scope, content_hash, source_uri, authority)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cid,
                        tenant_id,
                        analyst_id,
                        concept_id,
                        i,
                        concept.title[:256],
                        ch,
                        ej,
                        embedding_model,
                        now,
                        _OKF_KIND,
                        concept_id,
                        bundle_scope,
                        concept.content_hash,
                        concept.source_uri,
                        authority,
                    ),
                )
            indexed += 1
        c.commit()
    return indexed


async def index_okf_bundle_async(
    http: Any,
    bundle: ParsedBundle,
    *,
    use_embeddings: bool,
    api_key: str,
    base_url: str,
    embed_model: str,
) -> int:
    total = 0
    for concept in bundle.concepts.values():
        text = _okf_index_text(concept)
        chunks = _chunk_text(text) or [concept.title]
        vecs: list[list[float]] | None = None
        model: str | None = None
        if use_embeddings and api_key:
            try:
                vecs = await emb_mod.embed_texts(
                    http,
                    api_key=api_key,
                    base_url=base_url,
                    model=embed_model,
                    texts=chunks,
                )
                model = embed_model
            except Exception:
                vecs = None
                model = None
        sub = ParsedBundle(
            root=bundle.root,
            scope=bundle.scope,
            tenant_id=bundle.tenant_id,
            revision=bundle.revision,
            concepts={concept.concept_id: concept},
        )
        total += index_okf_concepts_sync(
            sub, embeddings=vecs, embedding_model=model
        )
    return total
