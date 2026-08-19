from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from investigation_agent import embeddings as emb_mod
from investigation_agent.okf_models import OkfConcept, ParsedBundle
from investigation_agent.store_backend import StoreConnection, connect_store, init_postgres_schema

"""
Investigation memos + OKF RAG (sqlite file or shared Postgres schema).
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
_conn: StoreConnection | None = None


@dataclass(frozen=True)
class _OkfIndexRow:
    chunk_id: str
    tenant_id: str
    analyst_id: str
    doc_id: str
    chunk_index: int
    title: str
    text: str
    embedding_json: str | None
    embedding_model: str | None
    created_at: float
    knowledge_kind: str
    concept_id: str
    bundle_scope: str
    content_hash: str
    source_uri: str
    authority: int


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


def _get_conn() -> StoreConnection:
    global _conn
    with _lock:
        if _conn is None:
            _conn = connect_store(sqlite_path=db_path(), init_schema=_init_schema)
        return _conn


def _init_schema(c: StoreConnection) -> None:
    if c.dialect == "postgres":
        init_postgres_schema(c)
        return
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


def _migrate_schema(c: StoreConnection) -> None:
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
    """Open the RAG store and execute a minimal query."""
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


def _trim_docs(c: StoreConnection, tenant_id: str, analyst_id: str) -> None:
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


def _prune_expired(c: StoreConnection, tenant_id: str, analyst_id: str, cutoff: float) -> None:
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
    with _lock:
        # ponytail: separate subqueries so the memo LIMIT cannot crowd out OKF rows
        rows = c.execute(
            """
            SELECT doc_id, chunk_index, title, text, embedding_json,
                   knowledge_kind, concept_id, bundle_scope, content_hash, source_uri, authority
            FROM (
              SELECT doc_id, chunk_index, title, text, embedding_json,
                     knowledge_kind, concept_id, bundle_scope, content_hash, source_uri, authority
              FROM knowledge_chunks
              WHERE tenant_id = ? AND analyst_id = ? AND knowledge_kind = ? AND created_at >= ?
              ORDER BY created_at DESC
              LIMIT ?
            ) AS memo_scan
            UNION ALL
            SELECT doc_id, chunk_index, title, text, embedding_json,
                   knowledge_kind, concept_id, bundle_scope, content_hash, source_uri, authority
            FROM knowledge_chunks
            WHERE tenant_id = ? AND analyst_id = ? AND knowledge_kind = ?
            UNION ALL
            SELECT doc_id, chunk_index, title, text, embedding_json,
                   knowledge_kind, concept_id, bundle_scope, content_hash, source_uri, authority
            FROM knowledge_chunks
            WHERE tenant_id = ? AND analyst_id = ? AND knowledge_kind = ?
            """,
            (
                tenant_id,
                analyst_id,
                _MEMO_KIND,
                cutoff,
                _MAX_CHUNKS_SCAN,
                tenant_id,
                _OKF_ANALYST_ID,
                _OKF_KIND,
                _SHARED_TENANT_ID,
                _OKF_ANALYST_ID,
                _OKF_KIND,
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
    # ponytail: separate caps so stale/dropped OKF rows don't crowd out memo results
    okf = [x for x in scored if x[1].get("knowledge_kind") == _OKF_KIND][:lim]
    memo = [x for x in scored if x[1].get("knowledge_kind") != _OKF_KIND][:lim]
    merged = sorted(okf + memo, key=lambda x: -x[0])
    return [x[1] for x in merged]


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
    purge_missing: bool = True,
) -> int:
    """Index approved concepts from a parsed bundle; returns count of concepts indexed.

    When *purge_missing* is True (default), OKF rows for concept IDs in the same
    bundle scope that are no longer in the bundle's approved set are deleted.
    """
    if embeddings is not None and len(bundle.concepts) > 1:
        raise ValueError("embeddings can only be supplied for single-concept bundles")
    tenant_id, authority = _okf_tenant_for_bundle(bundle)
    analyst_id = _OKF_ANALYST_ID
    bundle_scope = bundle.scope
    if embeddings is not None:
        approved = [c for c in bundle.concepts.values() if c.approval_status == "approved"]
        if len(approved) > 1:
            raise ValueError(
                "embeddings argument only supported for single-concept bundles; "
                "use prepare_okf_index_rows_async for multi-concept bundles"
            )
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
                embedding_json = json.dumps(embeddings[i]) if embeddings is not None else None
                _insert_okf_index_row(
                    c,
                    _okf_index_row(
                        tenant_id=tenant_id,
                        authority=authority,
                        bundle_scope=bundle_scope,
                        concept=concept,
                        chunk_index=i,
                        chunk_text=ch,
                        embedding_json=embedding_json,
                        embedding_model=embedding_model,
                        created_at=now,
                    ),
                )
            indexed += 1
        if purge_missing:
            _purge_orphan_okf_rows(c, tenant_id, analyst_id, bundle_scope, bundle)
        c.commit()
    return indexed


def _purge_orphan_okf_rows(
    c: StoreConnection,
    tenant_id: str,
    analyst_id: str,
    bundle_scope: str,
    bundle: ParsedBundle,
) -> None:
    """Delete OKF index rows whose concept_id is no longer approved in the bundle."""
    approved_ids = tuple(
        cid for cid, concept in bundle.concepts.items() if concept.approval_status == "approved"
    )
    if approved_ids:
        placeholders = ",".join("?" * len(approved_ids))
        c.execute(
            f"""
            DELETE FROM knowledge_chunks
            WHERE tenant_id = ? AND analyst_id = ? AND knowledge_kind = ?
              AND bundle_scope = ? AND concept_id NOT IN ({placeholders})
            """,
            (tenant_id, analyst_id, _OKF_KIND, bundle_scope, *approved_ids),
        )
    else:
        c.execute(
            """
            DELETE FROM knowledge_chunks
            WHERE tenant_id = ? AND analyst_id = ? AND knowledge_kind = ? AND bundle_scope = ?
            """,
            (tenant_id, analyst_id, _OKF_KIND, bundle_scope),
        )


def replace_okf_index_rows_sync(rows: tuple[_OkfIndexRow, ...]) -> None:
    """Replace all derived OKF rows atomically."""
    c = _get_conn()
    with _lock:
        try:
            c.execute("BEGIN IMMEDIATE")
            c.execute(
                "DELETE FROM knowledge_chunks WHERE knowledge_kind = ?",
                (_OKF_KIND,),
            )
            for row in rows:
                _insert_okf_index_row(c, row)
            c.commit()
        except Exception:
            c.rollback()
            raise


async def prepare_okf_index_rows_async(
    http: Any,
    bundles: tuple[ParsedBundle, ...],
    *,
    use_embeddings: bool,
    api_key: str,
    base_url: str,
    embed_model: str,
) -> tuple[tuple[_OkfIndexRow, ...], int]:
    rows: list[_OkfIndexRow] = []
    indexed = 0
    now = time.time()
    for bundle in bundles:
        tenant_id, authority = _okf_tenant_for_bundle(bundle)
        for concept in bundle.concepts.values():
            if concept.approval_status != "approved":
                continue
            chunks = _chunk_text(_okf_index_text(concept)) or [concept.title]
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
            if vecs is not None and len(vecs) != len(chunks):
                raise ValueError("embeddings length must match chunk count")
            for i, chunk in enumerate(chunks):
                embedding_json = json.dumps(vecs[i]) if vecs is not None else None
                rows.append(
                    _okf_index_row(
                        tenant_id=tenant_id,
                        authority=authority,
                        bundle_scope=bundle.scope,
                        concept=concept,
                        chunk_index=i,
                        chunk_text=chunk,
                        embedding_json=embedding_json,
                        embedding_model=model,
                        created_at=now,
                    )
                )
            indexed += 1
    return tuple(rows), indexed


async def replace_okf_bundles_async(
    http: Any,
    bundles: tuple[ParsedBundle, ...],
    *,
    use_embeddings: bool,
    api_key: str,
    base_url: str,
    embed_model: str,
) -> int:
    rows, indexed = await prepare_okf_index_rows_async(
        http,
        bundles,
        use_embeddings=use_embeddings,
        api_key=api_key,
        base_url=base_url,
        embed_model=embed_model,
    )
    replace_okf_index_rows_sync(rows)
    return indexed


def _okf_index_row(
    *,
    tenant_id: str,
    authority: int,
    bundle_scope: str,
    concept: OkfConcept,
    chunk_index: int,
    chunk_text: str,
    embedding_json: str | None,
    embedding_model: str | None,
    created_at: float,
) -> _OkfIndexRow:
    return _OkfIndexRow(
        chunk_id=f"okf:{tenant_id}:{concept.concept_id}:{chunk_index}",
        tenant_id=tenant_id,
        analyst_id=_OKF_ANALYST_ID,
        doc_id=concept.concept_id,
        chunk_index=chunk_index,
        title=concept.title[:256],
        text=chunk_text,
        embedding_json=embedding_json,
        embedding_model=embedding_model,
        created_at=created_at,
        knowledge_kind=_OKF_KIND,
        concept_id=concept.concept_id,
        bundle_scope=bundle_scope,
        content_hash=concept.content_hash,
        source_uri=concept.source_uri,
        authority=authority,
    )


def _insert_okf_index_row(c: StoreConnection, row: _OkfIndexRow) -> None:
    c.execute(
        """
        INSERT INTO knowledge_chunks
        (chunk_id, tenant_id, analyst_id, doc_id, chunk_index, title, text,
         embedding_json, embedding_model, created_at, knowledge_kind, concept_id,
         bundle_scope, content_hash, source_uri, authority)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.chunk_id,
            row.tenant_id,
            row.analyst_id,
            row.doc_id,
            row.chunk_index,
            row.title,
            row.text,
            row.embedding_json,
            row.embedding_model,
            row.created_at,
            row.knowledge_kind,
            row.concept_id,
            row.bundle_scope,
            row.content_hash,
            row.source_uri,
            row.authority,
        ),
    )


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
            sub, embeddings=vecs, embedding_model=model, purge_missing=False
        )
    tenant_id, _ = _okf_tenant_for_bundle(bundle)
    c = _get_conn()
    with _lock:
        _purge_orphan_okf_rows(c, tenant_id, _OKF_ANALYST_ID, bundle.scope, bundle)
        c.commit()
    return total
