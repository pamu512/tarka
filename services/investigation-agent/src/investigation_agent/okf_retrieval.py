from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from collections.abc import AsyncIterator
from typing import Any, Awaitable, Callable

from investigation_agent.config import settings
from investigation_agent.okf_models import OkfConcept
from investigation_agent.okf_registry import ConceptHit, OkfRegistry

_DEFAULT_LIMIT = 5
_STAGE_RANK = {"exact": 0, "expand": 1, "rag": 2}
_AUTHORITY_RANK = {"memo_rag": 0, "shared_okf": 1, "tenant_okf": 2}


@dataclass(frozen=True)
class KnowledgeResult:
    text: str
    authority: str
    concept_id: str | None
    content_hash: str | None
    evidence_ids: tuple[str, ...]
    retrieval_path: tuple[str, ...]
    score: float
    stale: bool
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeRetrievalResult:
    results: tuple[KnowledgeResult, ...]
    retrieval_mode: str
    conflicts: tuple[str, ...]
    abstain: bool
    bundle_revision: str


@dataclass(frozen=True)
class _Candidate:
    text: str
    authority: str
    concept_id: str | None
    content_hash: str | None
    evidence_ids: tuple[str, ...]
    retrieval_path: tuple[str, ...]
    score: float
    stale: bool
    source_uri: str | None
    stage: str
    metadata: dict[str, Any]


def retrieve_knowledge(
    *,
    registry: OkfRegistry,
    tenant_id: str,
    analyst_id: str,
    query: str,
    limit: int = _DEFAULT_LIMIT,
    rag_search: Callable[..., dict[str, Any]] | None = None,
    max_depth: int | None = None,
    max_concepts: int | None = None,
) -> KnowledgeRetrievalResult:
    exact_expand = _exact_and_expand_candidates(
        registry=registry,
        tenant_id=tenant_id,
        query=query,
        max_depth=max_depth,
        max_concepts=max_concepts,
    )
    rag_data: dict[str, Any] | None = None
    rag_candidates: list[_Candidate] = []
    normalized_limit = _normalize_limit(limit)
    if rag_search is not None and len(exact_expand) < normalized_limit:
        rag_data = _normalize_rag_payload(
            rag_search(
                tenant_id=tenant_id,
                analyst_id=analyst_id,
                query=query,
                limit=normalized_limit - len(exact_expand),
            )
        )
        rag_candidates = _rag_candidates(
            registry=registry,
            tenant_id=tenant_id,
            hits=rag_data["hits"],
        )
    return _finalize_result(
        registry=registry,
        tenant_id=tenant_id,
        limit=normalized_limit,
        exact_expand=exact_expand,
        rag_candidates=rag_candidates,
        rag_data=rag_data,
    )


async def retrieve_knowledge_async(
    *,
    registry: OkfRegistry,
    tenant_id: str,
    analyst_id: str,
    query: str,
    limit: int = _DEFAULT_LIMIT,
    rag_search: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    max_depth: int | None = None,
    max_concepts: int | None = None,
    generation_gate: asyncio.Lock | None = None,
) -> KnowledgeRetrievalResult:
    async with _maybe_generation_gate(generation_gate):
        exact_expand = _exact_and_expand_candidates(
            registry=registry,
            tenant_id=tenant_id,
            query=query,
            max_depth=max_depth,
            max_concepts=max_concepts,
        )
        rag_data: dict[str, Any] | None = None
        rag_candidates: list[_Candidate] = []
        normalized_limit = _normalize_limit(limit)
        if rag_search is not None and len(exact_expand) < normalized_limit:
            rag_data = _normalize_rag_payload(
                await rag_search(
                    tenant_id=tenant_id,
                    analyst_id=analyst_id,
                    query=query,
                    limit=normalized_limit - len(exact_expand),
                )
            )
            rag_candidates = _rag_candidates(
                registry=registry,
                tenant_id=tenant_id,
                hits=rag_data["hits"],
            )
        return _finalize_result(
            registry=registry,
            tenant_id=tenant_id,
            limit=normalized_limit,
            exact_expand=exact_expand,
            rag_candidates=rag_candidates,
            rag_data=rag_data,
        )


@asynccontextmanager
async def _maybe_generation_gate(generation_gate: asyncio.Lock | None) -> AsyncIterator[None]:
    if generation_gate is None:
        yield
        return
    async with generation_gate:
        yield


def _normalize_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = _DEFAULT_LIMIT
    return max(1, min(value, 15))


def _normalize_rag_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"hits": [], "retrieval_mode": "keyword"}
    hits = payload.get("hits")
    return {
        "hits": hits if isinstance(hits, list) else [],
        "retrieval_mode": str(payload.get("retrieval_mode") or "keyword"),
    }


def _exact_and_expand_candidates(
    *,
    registry: OkfRegistry,
    tenant_id: str,
    query: str,
    max_depth: int | None,
    max_concepts: int | None,
) -> list[_Candidate]:
    exact_hits = registry.resolve(tenant_id, query)
    raw: list[_Candidate] = [_candidate_from_concept_hit(hit, stage="exact") for hit in exact_hits]
    if exact_hits:
        expanded_hits = registry.expand(
            tenant_id,
            [hit.concept.concept_id for hit in exact_hits],
            max_depth=_effective_max_depth(max_depth),
            max_concepts=_effective_max_concepts(max_concepts),
        )
        raw.extend(_candidate_from_concept_hit(hit, stage="expand") for hit in expanded_hits)
    return _dedupe_and_sort(raw)


def _effective_max_depth(max_depth: int | None) -> int:
    if max_depth is None:
        return settings.okf_max_link_depth
    return max(0, min(int(max_depth), settings.okf_max_link_depth))


def _effective_max_concepts(max_concepts: int | None) -> int:
    if max_concepts is None:
        return settings.okf_max_concepts
    return max(1, min(int(max_concepts), settings.okf_max_concepts))


def _candidate_from_concept_hit(hit: ConceptHit, *, stage: str) -> _Candidate:
    concept = hit.concept
    # Registry hits come from the current loaded snapshot, so their hashes are canonical
    # for this tenant view and can never be "stale" within the retrieval decision.
    return _Candidate(
        text=_concept_text(concept),
        authority=_okf_authority(hit.authority),
        concept_id=concept.concept_id,
        content_hash=concept.content_hash,
        evidence_ids=concept.evidence_ids,
        retrieval_path=hit.retrieval_path,
        score=float(hit.score),
        stale=False,
        source_uri=concept.source_uri,
        stage=stage,
        metadata={},
    )


def _concept_text(concept: OkfConcept) -> str:
    parts = [concept.title]
    if concept.description:
        parts.append(concept.description)
    if concept.body:
        parts.append(concept.body)
    return "\n\n".join(parts)


def _okf_authority(authority: str) -> str:
    return "tenant_okf" if authority == "tenant" else "shared_okf"


def _rag_candidates(
    *,
    registry: OkfRegistry,
    tenant_id: str,
    hits: list[Any],
) -> list[_Candidate]:
    lookup_cache: dict[str, ConceptHit | None] = {}
    candidates: list[_Candidate] = []
    for raw_hit in hits:
        if not isinstance(raw_hit, dict):
            continue
        candidate = _candidate_from_rag_hit(
            registry=registry,
            tenant_id=tenant_id,
            hit=raw_hit,
            lookup_cache=lookup_cache,
        )
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _candidate_from_rag_hit(
    *,
    registry: OkfRegistry,
    tenant_id: str,
    hit: dict[str, Any],
    lookup_cache: dict[str, ConceptHit | None],
) -> _Candidate | None:
    knowledge_kind = str(hit.get("knowledge_kind") or "memo").strip().lower()
    concept_id = str(hit.get("concept_id") or "").strip()
    score = _as_float(hit.get("score"))
    if knowledge_kind == "okf" and concept_id:
        current_hit = _lookup_concept_hit(
            registry=registry,
            tenant_id=tenant_id,
            concept_id=concept_id,
            lookup_cache=lookup_cache,
        )
        if current_hit is None:
            return None
        indexed_hash = str(hit.get("content_hash") or "").strip() or None
        return _Candidate(
            text=_concept_text(current_hit.concept),
            authority=_okf_authority(current_hit.authority),
            concept_id=current_hit.concept.concept_id,
            content_hash=indexed_hash or current_hit.concept.content_hash,
            evidence_ids=current_hit.concept.evidence_ids,
            retrieval_path=(current_hit.concept.concept_id,),
            score=score,
            stale=indexed_hash != current_hit.concept.content_hash,
            source_uri=str(hit.get("source_uri") or current_hit.concept.source_uri).strip()
            or current_hit.concept.source_uri,
            stage="rag",
            metadata=_rag_metadata(hit),
        )

    title = str(hit.get("title") or "").strip()
    snippet = str(hit.get("snippet") or "").strip()
    text = snippet or title
    return _Candidate(
        text=text,
        authority="memo_rag",
        concept_id=None,
        content_hash=str(hit.get("content_hash") or "").strip() or None,
        evidence_ids=(),
        retrieval_path=(),
        score=score,
        stale=False,
        source_uri=str(hit.get("source_uri") or "").strip() or None,
        stage="rag",
        metadata=_rag_metadata(hit),
    )


def _rag_metadata(hit: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "doc_id",
        "title",
        "chunk_index",
        "snippet",
        "authority",
        "semantic_score",
        "keyword_hits",
        "knowledge_kind",
        "bundle_scope",
        "source_uri",
    )
    return {key: hit[key] for key in keys if key in hit}


def _lookup_concept_hit(
    *,
    registry: OkfRegistry,
    tenant_id: str,
    concept_id: str,
    lookup_cache: dict[str, ConceptHit | None],
) -> ConceptHit | None:
    cached = lookup_cache.get(concept_id)
    if concept_id in lookup_cache:
        return cached
    hits = registry.expand(
        tenant_id,
        [concept_id],
        max_depth=0,
        max_concepts=1,
    )
    current = next((hit for hit in hits if hit.concept.concept_id == concept_id), None)
    lookup_cache[concept_id] = current
    return current


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _dedupe_and_sort(candidates: list[_Candidate]) -> list[_Candidate]:
    ordered = sorted(candidates, key=_candidate_sort_key)
    deduped: list[_Candidate] = []
    seen: set[tuple[str, str]] = set()
    for candidate in ordered:
        key = _dedupe_key(candidate)
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
        deduped.append(candidate)
    return deduped


def _candidate_sort_key(candidate: _Candidate) -> tuple[Any, ...]:
    return (
        -_AUTHORITY_RANK.get(candidate.authority, -1),
        -int(bool(candidate.evidence_ids)),
        _STAGE_RANK.get(candidate.stage, 99),
        -candidate.score,
        candidate.concept_id or "",
        candidate.content_hash or "",
        candidate.text,
    )


def _dedupe_key(candidate: _Candidate) -> tuple[str, str] | None:
    if candidate.concept_id:
        return ("concept", candidate.concept_id)
    if candidate.content_hash:
        return ("content_hash", candidate.content_hash)
    return None


def _finalize_result(
    *,
    registry: OkfRegistry,
    tenant_id: str,
    limit: int,
    exact_expand: list[_Candidate],
    rag_candidates: list[_Candidate],
    rag_data: dict[str, Any] | None,
) -> KnowledgeRetrievalResult:
    all_candidates = [*exact_expand, *rag_candidates]
    conflicts = _detect_conflicts(all_candidates)
    combined = _dedupe_and_sort([candidate for candidate in all_candidates if not candidate.stale])
    authoritative = [
        candidate
        for candidate in combined
        if candidate.authority in {"tenant_okf", "shared_okf"} and not candidate.stale
    ]
    retrieval_mode = _compose_retrieval_mode(combined, rag_data)
    results = tuple(
        KnowledgeResult(
            text=candidate.text,
            authority=candidate.authority,
            concept_id=candidate.concept_id,
            content_hash=candidate.content_hash,
            evidence_ids=candidate.evidence_ids,
            retrieval_path=candidate.retrieval_path,
            score=candidate.score,
            stale=candidate.stale,
            metadata=dict(candidate.metadata),
        )
        for candidate in combined[:limit]
    )
    return KnowledgeRetrievalResult(
        results=results,
        retrieval_mode=retrieval_mode,
        conflicts=conflicts,
        abstain=not authoritative or bool(conflicts),
        bundle_revision=registry.snapshot_revision(tenant_id),
    )


def _compose_retrieval_mode(candidates: list[_Candidate], rag_data: dict[str, Any] | None) -> str:
    parts: list[str] = []
    if any(candidate.stage == "exact" for candidate in candidates):
        parts.append("exact")
    if any(candidate.stage == "expand" for candidate in candidates):
        parts.append("expand")
    if rag_data is not None:
        parts.append(str(rag_data.get("retrieval_mode") or "keyword"))
    return "+".join(parts) if parts else "keyword"


def _detect_conflicts(candidates: list[_Candidate]) -> tuple[str, ...]:
    grouped: dict[tuple[str, str], list[_Candidate]] = {}
    for candidate in candidates:
        if candidate.authority not in {"tenant_okf", "shared_okf"}:
            continue
        if not candidate.source_uri or not candidate.concept_id or not candidate.content_hash:
            continue
        grouped.setdefault((candidate.authority, candidate.source_uri), []).append(candidate)

    conflicts: list[str] = []
    for (authority, source_uri), entries in grouped.items():
        hashes = {entry.content_hash for entry in entries}
        if len(hashes) <= 1:
            continue
        concept_ids = [entry.concept_id for entry in entries if entry.concept_id]
        if len(set(concept_ids)) == len(entries):
            labels = sorted({concept_id for concept_id in concept_ids if concept_id})
        else:
            labels = sorted(
                {
                    f"{entry.concept_id}[{entry.content_hash}]"
                    for entry in entries
                    if entry.concept_id and entry.content_hash
                }
            )
        conflicts.append(f"{authority} conflict for {source_uri}: " + " != ".join(labels))
    return tuple(sorted(conflicts))
