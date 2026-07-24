from __future__ import annotations

import hashlib
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
        return (root / target_href.lstrip("/")).resolve(strict=False)
    return (source.parent / target_href).resolve(strict=False)


def _resolve_link_ids(body: str, source: Path, root: Path) -> tuple[str, ...]:
    link_ids: list[str] = []
    for match in _LINK.finditer(body):
        href = match.group(1)
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
    path: Path, root: Path, scope: str, tenant_id: str | None
) -> OkfConcept:
    raw = path.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(raw)
    if not match:
        raise OkfParseError("frontmatter_missing", path, "concept requires YAML frontmatter")
    meta = yaml.safe_load(match.group(1))
    if not isinstance(meta, dict) or not str(meta.get("type") or "").strip():
        raise OkfParseError("type_missing", path, "frontmatter.type is required")
    concept_id = _concept_id_for(path, root)
    links = _resolve_link_ids(match.group(2), path, root)
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
        approval_status=str(meta["approval_status"]).strip(),
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
        f"{concept_id}:{concept.content_hash}"
        for concept_id, concept in sorted(concepts.items())
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


def validate_bundle(
    root: Path, *, scope: str, tenant_id: str | None
) -> BundleValidation:
    root = root.resolve()
    issues: list[BundleIssue] = []
    issues.extend(_check_reserved_files(root))

    concepts: dict[str, OkfConcept] = {}
    concept_paths = _iter_concept_paths(root)

    for path in concept_paths:
        try:
            concept = parse_concept(path, root, scope, tenant_id)
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

    if not issues:
        for concept in concepts.values():
            for link_id in concept.links:
                if link_id not in concepts:
                    issues.append(
                        BundleIssue(
                            "link_target_missing",
                            concept.path.as_posix(),
                            f"missing link target: {link_id}",
                        )
                    )

    if issues:
        return BundleValidation(valid=False, issues=tuple(issues), bundle=None)

    bundle = ParsedBundle(
        root=root,
        scope=scope,
        tenant_id=tenant_id,
        revision=_bundle_revision(concepts),
        concepts=concepts,
    )
    return BundleValidation(valid=True, issues=(), bundle=bundle)


def parse_bundle(root: Path, *, scope: str, tenant_id: str | None) -> ParsedBundle:
    result = validate_bundle(root, scope=scope, tenant_id=tenant_id)
    if not result.valid or result.bundle is None:
        summary = "; ".join(f"{issue.code}@{issue.path}" for issue in result.issues)
        raise ValueError(summary or "invalid OKF bundle")
    return result.bundle
