from __future__ import annotations

import hashlib
import re
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from investigation_agent.okf_models import BundleIssue, OkfConcept, ParsedBundle
from investigation_agent.okf_parser import validate_bundle

_EMPTY_REVISION = hashlib.sha256(b"").hexdigest()


def _bundle_revision(concepts: dict[str, OkfConcept]) -> str:
    payload = "\n".join(
        f"{concept_id}:{concept.content_hash}"
        for concept_id, concept in sorted(concepts.items())
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


@dataclass(frozen=True)
class ConceptHit:
    concept: OkfConcept
    authority: str
    retrieval_path: tuple[str, ...]
    score: float


@dataclass(frozen=True)
class RegistryReloadResult:
    activated: bool
    revision: str
    issues: tuple[BundleIssue, ...]


@dataclass(frozen=True)
class _TenantView:
    revision: str
    concepts: dict[str, OkfConcept]
    authority: dict[str, str]


@dataclass(frozen=True)
class _RegistrySnapshot:
    revision: str
    shared: ParsedBundle | None
    tenants: dict[str, ParsedBundle]
    views: dict[str, _TenantView]


@dataclass(frozen=True)
class _LoadCandidate:
    issues: tuple[BundleIssue, ...]
    snapshot: _RegistrySnapshot


class OkfRegistry:
    def __init__(self, *, shared_root: Path, tenant_root: Path) -> None:
        self._shared_root = shared_root.resolve()
        self._tenant_root = tenant_root.resolve()
        self._lock = threading.Lock()
        self._snapshot = _RegistrySnapshot(
            revision=_EMPTY_REVISION,
            shared=None,
            tenants={},
            views={},
        )

    def reload(self) -> RegistryReloadResult:
        candidate = self._load_all()
        if candidate.issues:
            return RegistryReloadResult(
                False, self._snapshot.revision, candidate.issues
            )
        with self._lock:
            self._snapshot = candidate.snapshot
        return RegistryReloadResult(True, candidate.snapshot.revision, ())

    def snapshot_revision(self, tenant_id: str) -> str:
        view = self._snapshot.views.get(tenant_id)
        if view is not None:
            return view.revision
        if self._snapshot.shared is not None:
            return self._snapshot.shared.revision
        return self._snapshot.revision

    def resolve(self, tenant_id: str, query: str) -> list[ConceptHit]:
        view = self._view_for(tenant_id)
        if view is None:
            return []
        normalized_query = _normalize_text(query)
        if not normalized_query:
            return []
        hits: list[ConceptHit] = []
        for concept_id, concept in view.concepts.items():
            score = self._match_score(concept_id, concept, normalized_query)
            if score <= 0:
                continue
            hits.append(
                ConceptHit(
                    concept=concept,
                    authority=view.authority[concept_id],
                    retrieval_path=(concept_id,),
                    score=score,
                )
            )
        hits.sort(key=lambda hit: (-hit.score, hit.concept.concept_id))
        return hits

    def expand(
        self,
        tenant_id: str,
        concept_ids: tuple[str, ...] | list[str],
        *,
        max_depth: int,
        max_concepts: int,
    ) -> list[ConceptHit]:
        view = self._view_for(tenant_id)
        if view is None or max_concepts <= 0:
            return []

        queue: deque[tuple[str, int, tuple[str, ...]]] = deque()
        for seed in concept_ids:
            if seed in view.concepts:
                queue.append((seed, 0, (seed,)))

        visited: set[str] = set()
        hits: list[ConceptHit] = []

        while queue and len(hits) < max_concepts:
            concept_id, depth, path = queue.popleft()
            if concept_id in visited:
                continue
            concept = view.concepts.get(concept_id)
            if concept is None:
                continue
            visited.add(concept_id)
            hits.append(
                ConceptHit(
                    concept=concept,
                    authority=view.authority[concept_id],
                    retrieval_path=path,
                    score=1.0,
                )
            )
            if depth >= max_depth:
                continue
            for link_id in concept.links:
                if link_id in visited:
                    continue
                if link_id not in view.concepts:
                    continue
                queue.append((link_id, depth + 1, path + (link_id,)))

        return hits

    def _view_for(self, tenant_id: str) -> _TenantView | None:
        view = self._snapshot.views.get(tenant_id)
        if view is not None:
            return view
        if self._snapshot.shared is None:
            return None
        return self._shared_only_view()

    def _match_score(
        self, concept_id: str, concept: OkfConcept, normalized_query: str
    ) -> float:
        if _normalize_text(concept_id) == normalized_query:
            return 1.0
        if _normalize_text(concept.title) == normalized_query:
            return 0.9
        for tag in concept.tags:
            if _normalize_text(tag) == normalized_query:
                return 0.8
        return 0.0

    def _load_all(self) -> _LoadCandidate:
        issues: list[BundleIssue] = []
        shared_validation = validate_bundle(
            self._shared_root, scope="shared", tenant_id=None
        )
        if not shared_validation.valid:
            issues.extend(shared_validation.issues)

        shared_bundle = shared_validation.bundle
        tenant_bundles: dict[str, ParsedBundle] = {}

        if self._tenant_root.is_dir():
            for tenant_dir in sorted(self._tenant_root.iterdir()):
                if not tenant_dir.is_dir():
                    continue
                tenant_id = tenant_dir.name
                tenant_validation = validate_bundle(
                    tenant_dir,
                    scope="tenant",
                    tenant_id=tenant_id,
                    shared_bundle=shared_bundle,
                )
                if not tenant_validation.valid:
                    issues.extend(tenant_validation.issues)
                    continue
                if tenant_validation.bundle is not None:
                    tenant_bundles[tenant_id] = tenant_validation.bundle

        if issues:
            return _LoadCandidate(tuple(issues), self._snapshot)

        views = self._build_views(shared_bundle, tenant_bundles)
        global_revision = self._global_revision(shared_bundle, tenant_bundles)
        snapshot = _RegistrySnapshot(
            revision=global_revision,
            shared=shared_bundle,
            tenants=tenant_bundles,
            views=views,
        )
        return _LoadCandidate((), snapshot)

    def _shared_only_view(self) -> _TenantView:
        assert self._snapshot.shared is not None
        concepts = dict(self._snapshot.shared.concepts)
        return _TenantView(
            revision=_bundle_revision(concepts),
            concepts=concepts,
            authority={cid: "shared" for cid in concepts},
        )

    def _build_views(
        self,
        shared_bundle: ParsedBundle | None,
        tenant_bundles: dict[str, ParsedBundle],
    ) -> dict[str, _TenantView]:
        shared_concepts = dict(shared_bundle.concepts) if shared_bundle else {}
        shared_authority = {cid: "shared" for cid in shared_concepts}
        views: dict[str, _TenantView] = {}

        for tenant_id, tenant_bundle in tenant_bundles.items():
            merged = dict(shared_concepts)
            authority = dict(shared_authority)
            for cid, concept in tenant_bundle.concepts.items():
                merged[cid] = concept
                authority[cid] = "tenant"
            views[tenant_id] = _TenantView(
                revision=_bundle_revision(merged),
                concepts=merged,
                authority=authority,
            )
        return views

    def _global_revision(
        self,
        shared_bundle: ParsedBundle | None,
        tenant_bundles: dict[str, ParsedBundle],
    ) -> str:
        parts = [shared_bundle.revision if shared_bundle else ""]
        for tenant_id in sorted(tenant_bundles):
            parts.append(f"{tenant_id}:{tenant_bundles[tenant_id].revision}")
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
