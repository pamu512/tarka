from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import yaml

from investigation_agent.okf_models import (
    BundleIssue,
    BundleValidation,
    OkfConcept,
    OkfParseError,
    ParsedBundle,
)

_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n(.*)\Z", re.DOTALL)
_LINK = re.compile(r"\[[^\]]+\]\(([^)]+\.md(?:#[^)]+)?)\)")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_RESERVED_NAMES = frozenset({"index.md", "log.md"})
_APPROVED_STATUS = "approved"
_SHARED_LOGICAL_PREFIX = "/shared/"
_SOURCE_MANIFEST_NAME = "source-manifest.json"
_SOURCE_MANIFEST_SCHEMA = "tarka.okf_source_manifest/v1"
_SOURCE_SNAPSHOT_SCHEMA = "tarka.okf_source_snapshot/v1"
_SOURCE_SNAPSHOT_ROOT = "_provenance/sources"


class _DuplicateJsonKey(ValueError):
    pass


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in pairs:
        if key in out:
            raise _DuplicateJsonKey(key)
        out[key] = value
    return out


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=True))
        return True
    except ValueError:
        return False


def _concept_id_for(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).with_suffix("").as_posix()


def _resolve_link_target(href: str, source: Path, root: Path) -> Path:
    target_href = href.split("#", 1)[0]
    if target_href.startswith("/"):
        raise OkfParseError(
            "link_not_relative",
            source,
            f"shared bundles require relative markdown links: {href}",
        )
    return (source.parent / target_href).resolve(strict=False)


def _shared_logical_concept_id(href: str, source: Path) -> str:
    target_href = href.split("#", 1)[0]
    if not target_href.startswith(_SHARED_LOGICAL_PREFIX):
        raise OkfParseError(
            "link_not_shared_logical",
            source,
            f"tenant bundles require /shared/<concept-id>.md links: {href}",
        )
    if ".." in Path(target_href).parts:
        raise OkfParseError(
            "link_outside_bundle",
            source,
            f"link target escapes bundle: {href}",
        )
    remainder = target_href[len(_SHARED_LOGICAL_PREFIX) :]
    if not remainder.endswith(".md") or remainder == ".md":
        raise OkfParseError(
            "link_not_shared_logical",
            source,
            f"tenant shared link must end with .md: {href}",
        )
    concept_id = remainder[: -len(".md")]
    if not concept_id or concept_id.startswith("/"):
        raise OkfParseError(
            "link_not_shared_logical",
            source,
            f"invalid shared logical link: {href}",
        )
    return concept_id


def _resolve_link_ids(
    body: str,
    source: Path,
    root: Path,
    *,
    scope: str,
    shared_concepts: dict[str, OkfConcept] | None,
) -> tuple[str, ...]:
    link_ids: list[str] = []
    for match in _LINK.finditer(body):
        href = match.group(1)
        target_href = href.split("#", 1)[0]
        if scope == "shared":
            if target_href.startswith(_SHARED_LOGICAL_PREFIX) or (
                target_href.startswith("/") and not target_href.startswith(_SHARED_LOGICAL_PREFIX)
            ):
                raise OkfParseError(
                    "link_not_relative",
                    source,
                    f"shared bundles require relative markdown links: {href}",
                )
            target = _resolve_link_target(href, source, root)
            if not _inside(target, root):
                raise OkfParseError(
                    "link_outside_bundle",
                    source,
                    f"link target escapes bundle: {href}",
                )
            link_ids.append(_concept_id_for(target, root))
            continue

        if target_href.startswith("/"):
            concept_id = _shared_logical_concept_id(href, source)
            if shared_concepts is None:
                raise OkfParseError(
                    "shared_bundle_required",
                    source,
                    "tenant bundle validation requires an approved shared bundle",
                )
            if concept_id not in shared_concepts:
                raise OkfParseError(
                    "link_target_missing",
                    source,
                    f"missing shared link target: {concept_id}",
                )
            link_ids.append(concept_id)
            continue

        target = _resolve_link_target(href, source, root)
        if not _inside(target, root):
            raise OkfParseError(
                "link_outside_bundle",
                source,
                f"link target escapes bundle: {href}",
            )
        link_ids.append(_concept_id_for(target, root))
    return tuple(link_ids)


def parse_concept(
    path: Path,
    root: Path,
    scope: str,
    tenant_id: str | None,
    *,
    shared_concepts: dict[str, OkfConcept] | None = None,
) -> OkfConcept:
    raw = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(raw)
    if not match:
        raise OkfParseError("frontmatter_missing", path, "concept requires YAML frontmatter")
    meta = yaml.safe_load(match.group(1))
    if not isinstance(meta, dict) or not str(meta.get("type") or "").strip():
        raise OkfParseError("type_missing", path, "frontmatter.type is required")
    concept_id = _concept_id_for(path, root)
    links = _resolve_link_ids(
        match.group(2),
        path,
        root,
        scope=scope,
        shared_concepts=shared_concepts,
    )
    required = (
        "source_uri",
        "source_content_hash",
        "approval_status",
        "approved_revision",
        "sensitivity",
        "tenant_scope",
    )
    missing = [key for key in required if not str(meta.get(key) or "").strip()]
    if missing:
        raise OkfParseError(
            "governance_field_missing",
            path,
            f"missing fields: {','.join(missing)}",
        )
    expected_scope = "shared" if scope == "shared" else str(tenant_id or "")
    if str(meta["tenant_scope"]).strip() != expected_scope:
        raise OkfParseError(
            "tenant_scope_mismatch",
            path,
            f"expected tenant_scope={expected_scope}",
        )
    approval_status = str(meta["approval_status"]).strip()
    if approval_status != _APPROVED_STATUS:
        raise OkfParseError(
            "approval_status_not_approved",
            path,
            f"approval_status must be {_APPROVED_STATUS!r}, got {approval_status!r}",
        )
    source_hash = str(meta["source_content_hash"]).strip().lower()
    if not _HASH.fullmatch(source_hash):
        raise OkfParseError(
            "source_hash_invalid",
            path,
            "source_content_hash must be SHA-256 hex",
        )
    tags_raw = meta.get("tags") or []
    evidence_raw = meta.get("evidence_ids") or []
    return OkfConcept(
        concept_id=concept_id,
        path=path.resolve(),
        concept_type=str(meta["type"]).strip(),
        title=str(meta.get("title") or concept_id).strip(),
        description=str(meta.get("description") or "").strip(),
        tags=tuple(str(x).strip() for x in tags_raw if str(x).strip()),
        timestamp=str(meta["timestamp"]).strip() if meta.get("timestamp") else None,
        source_uri=str(meta["source_uri"]).strip(),
        source_content_hash=source_hash,
        approval_status=approval_status,
        approved_revision=str(meta["approved_revision"]).strip(),
        sensitivity=str(meta["sensitivity"]).strip(),
        tenant_scope=str(meta["tenant_scope"]).strip(),
        evidence_ids=tuple(str(x).strip() for x in evidence_raw if str(x).strip()),
        body=match.group(2).strip(),
        links=links,
        content_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        frontmatter=dict(meta),
    )


def _bundle_revision(concepts: dict[str, OkfConcept]) -> str:
    payload = "\n".join(
        f"{concept_id}:{concept.content_hash}" for concept_id, concept in sorted(concepts.items())
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _iter_concept_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for path in sorted(root.rglob("*.md")):
        if path.name in _RESERVED_NAMES:
            continue
        if not _inside(path, root):
            continue
        paths.append(path)
    return paths


def _check_reserved_files(root: Path) -> list[BundleIssue]:
    issues: list[BundleIssue] = []
    root_resolved = root.resolve()
    for path in sorted(root.rglob("*.md")):
        if path.name not in _RESERVED_NAMES:
            continue
        if not _inside(path, root):
            continue
        if path.name == "index.md" and path.parent.resolve() == root_resolved:
            continue
        raw = path.read_text(encoding="utf-8")
        if _FRONTMATTER.match(raw):
            issues.append(
                BundleIssue(
                    "frontmatter_on_reserved",
                    path.as_posix(),
                    "frontmatter is only permitted on the bundle root index.md",
                )
            )
    return issues


def _validate_source_manifest(
    root: Path,
    concepts: dict[str, OkfConcept],
) -> list[BundleIssue]:
    path = root / _SOURCE_MANIFEST_NAME
    if not path.is_file():
        if not concepts:
            return []
        return [
            BundleIssue(
                "source_manifest_missing",
                path.as_posix(),
                "approved bundles with concepts require source-manifest.json",
            )
        ]
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except _DuplicateJsonKey as exc:
        return [
            BundleIssue(
                "source_manifest_duplicate",
                path.as_posix(),
                f"source manifest contains duplicate key: {exc}",
            )
        ]
    except (OSError, json.JSONDecodeError) as exc:
        return [
            BundleIssue(
                "source_manifest_invalid",
                path.as_posix(),
                f"source manifest is not valid JSON: {exc}",
            )
        ]
    if not isinstance(payload, dict) or payload.get("schema_id") != _SOURCE_MANIFEST_SCHEMA:
        return [
            BundleIssue(
                "source_manifest_invalid",
                path.as_posix(),
                f"source manifest schema_id must be {_SOURCE_MANIFEST_SCHEMA}",
            )
        ]
    entries = payload.get("sources")
    if not isinstance(entries, dict):
        return [
            BundleIssue(
                "source_manifest_invalid",
                path.as_posix(),
                "source manifest sources must be an object",
            )
        ]

    issues: list[BundleIssue] = []
    concepts_by_uri: dict[str, OkfConcept] = {}
    for concept in concepts.values():
        prior = concepts_by_uri.get(concept.source_uri)
        if prior is not None:
            issues.append(
                BundleIssue(
                    "source_uri_duplicate",
                    concept.path.as_posix(),
                    f"source_uri is shared with {prior.concept_id}: {concept.source_uri}",
                )
            )
            continue
        concepts_by_uri[concept.source_uri] = concept

    validated_sources: dict[str, tuple[str, str]] = {}
    used_snapshot_paths: set[str] = set()
    for source_uri, raw in sorted(entries.items()):
        if not isinstance(source_uri, str) or not source_uri.strip() or not isinstance(raw, dict):
            issues.append(
                BundleIssue(
                    "source_manifest_entry_invalid",
                    path.as_posix(),
                    "source manifest entries require a non-empty URI and object value",
                )
            )
            continue
        snapshot_rel = str(raw.get("snapshot_path") or "").strip()
        manifest_hash = str(raw.get("source_content_hash") or "").strip().lower()
        rel = Path(snapshot_rel)
        if (
            not snapshot_rel
            or rel.is_absolute()
            or ".." in rel.parts
            or not snapshot_rel.startswith(f"{_SOURCE_SNAPSHOT_ROOT}/")
            or rel.suffix != ".json"
        ):
            issues.append(
                BundleIssue(
                    "source_snapshot_path_invalid",
                    path.as_posix(),
                    f"invalid source snapshot path for {source_uri}",
                )
            )
            continue
        if snapshot_rel in used_snapshot_paths:
            issues.append(
                BundleIssue(
                    "source_snapshot_duplicate",
                    path.as_posix(),
                    f"source snapshot is referenced more than once: {snapshot_rel}",
                )
            )
        used_snapshot_paths.add(snapshot_rel)
        snapshot_path = (root / rel).resolve(strict=False)
        if not _inside(snapshot_path, root):
            issues.append(
                BundleIssue(
                    "source_snapshot_path_invalid",
                    path.as_posix(),
                    f"source snapshot escapes bundle for {source_uri}",
                )
            )
            continue
        if not snapshot_path.is_file():
            issues.append(
                BundleIssue(
                    "source_snapshot_missing",
                    snapshot_path.as_posix(),
                    f"source snapshot missing for {source_uri}",
                )
            )
            continue
        snapshot_bytes = snapshot_path.read_bytes()
        computed_hash = hashlib.sha256(snapshot_bytes).hexdigest()
        if not _HASH.fullmatch(manifest_hash) or manifest_hash != computed_hash:
            issues.append(
                BundleIssue(
                    "source_snapshot_hash_mismatch",
                    snapshot_path.as_posix(),
                    f"source snapshot hash differs from manifest for {source_uri}",
                )
            )
        try:
            snapshot_payload = json.loads(
                snapshot_bytes,
                object_pairs_hook=_reject_duplicate_json_keys,
            )
        except (_DuplicateJsonKey, json.JSONDecodeError, UnicodeDecodeError):
            snapshot_payload = None
        if (
            not isinstance(snapshot_payload, dict)
            or snapshot_payload.get("schema_id") != _SOURCE_SNAPSHOT_SCHEMA
            or str(snapshot_payload.get("source_uri") or "").strip() != source_uri
            or not isinstance(snapshot_payload.get("record"), dict)
        ):
            issues.append(
                BundleIssue(
                    "source_snapshot_invalid",
                    snapshot_path.as_posix(),
                    f"source snapshot schema or URI is invalid for {source_uri}",
                )
            )
        validated_sources[source_uri] = (computed_hash, snapshot_rel)

    for source_uri, concept in sorted(concepts_by_uri.items()):
        raw = entries.get(source_uri)
        if not isinstance(raw, dict):
            issues.append(
                BundleIssue(
                    "source_manifest_entry_missing",
                    concept.path.as_posix(),
                    f"source manifest has no provenance for {source_uri}",
                )
            )
            continue
        computed = validated_sources.get(source_uri)
        computed_hash = computed[0] if computed else ""
        if computed_hash != concept.source_content_hash:
            issues.append(
                BundleIssue(
                    "source_hash_mismatch",
                    concept.path.as_posix(),
                    f"source_content_hash differs from canonical snapshot for {concept.concept_id}",
                )
            )
    for source_uri in sorted(set(entries) - set(concepts_by_uri)):
        issues.append(
            BundleIssue(
                "source_manifest_orphan",
                path.as_posix(),
                f"source manifest references no concept: {source_uri}",
            )
        )
    snapshot_root = root / _SOURCE_SNAPSHOT_ROOT
    actual_snapshots = (
        {
            snapshot.relative_to(root).as_posix()
            for snapshot in snapshot_root.rglob("*.json")
            if snapshot.is_file() and _inside(snapshot, root)
        }
        if snapshot_root.is_dir()
        else set()
    )
    for snapshot_rel in sorted(actual_snapshots - used_snapshot_paths):
        issues.append(
            BundleIssue(
                "source_snapshot_orphan",
                (root / snapshot_rel).as_posix(),
                "source snapshot is not referenced by the manifest",
            )
        )
    return issues


def validate_bundle(
    root: Path,
    *,
    scope: str,
    tenant_id: str | None,
    shared_bundle: ParsedBundle | None = None,
) -> BundleValidation:
    root = root.resolve()
    issues: list[BundleIssue] = []
    issues.extend(_check_reserved_files(root))

    shared_concepts = shared_bundle.concepts if shared_bundle is not None else None

    concepts: dict[str, OkfConcept] = {}
    concept_paths = _iter_concept_paths(root)

    for path in concept_paths:
        try:
            concept = parse_concept(
                path,
                root,
                scope,
                tenant_id,
                shared_concepts=shared_concepts,
            )
        except OkfParseError as exc:
            issues.append(BundleIssue(exc.code, exc.path.as_posix(), exc.message))
            continue

        if concept.concept_id in concepts:
            issues.append(
                BundleIssue(
                    "duplicate_concept_id",
                    path.as_posix(),
                    f"duplicate concept id: {concept.concept_id}",
                )
            )
            continue
        concepts[concept.concept_id] = concept

    for concept in concepts.values():
        for link_id in concept.links:
            if link_id in concepts:
                continue
            if scope == "tenant" and shared_concepts and link_id in shared_concepts:
                continue
            issues.append(
                BundleIssue(
                    "link_target_missing",
                    concept.path.as_posix(),
                    f"missing link target: {link_id}",
                )
            )

    issues.extend(_validate_source_manifest(root, concepts))

    if issues:
        return BundleValidation(valid=False, issues=tuple(issues), bundle=None)

    backlink_sets: dict[str, set[str]] = {}
    for concept in concepts.values():
        for target_id in concept.links:
            backlink_sets.setdefault(target_id, set()).add(concept.concept_id)
    backlinks = {
        target_id: tuple(sorted(source_ids))
        for target_id, source_ids in sorted(backlink_sets.items())
    }
    bundle = ParsedBundle(
        root=root,
        scope=scope,
        tenant_id=tenant_id,
        revision=_bundle_revision(concepts),
        concepts=concepts,
        backlinks=backlinks,
    )
    return BundleValidation(valid=True, issues=(), bundle=bundle)


def parse_bundle(
    root: Path,
    *,
    scope: str,
    tenant_id: str | None,
    shared_bundle: ParsedBundle | None = None,
) -> ParsedBundle:
    result = validate_bundle(root, scope=scope, tenant_id=tenant_id, shared_bundle=shared_bundle)
    if not result.valid or result.bundle is None:
        summary = "; ".join(f"{issue.code}@{issue.path}" for issue in result.issues)
        raise ValueError(summary or "invalid OKF bundle")
    return result.bundle
