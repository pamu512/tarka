from dataclasses import dataclass
from pathlib import Path
from typing import Any


class OkfParseError(ValueError):
    def __init__(self, code: str, path: Path, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.path = path
        self.message = message


@dataclass(frozen=True)
class OkfConcept:
    concept_id: str
    path: Path
    concept_type: str
    title: str
    description: str
    tags: tuple[str, ...]
    timestamp: str | None
    source_uri: str
    source_content_hash: str
    approval_status: str
    approved_revision: str
    sensitivity: str
    tenant_scope: str
    evidence_ids: tuple[str, ...]
    body: str
    links: tuple[str, ...]
    content_hash: str
    frontmatter: dict[str, Any]


@dataclass(frozen=True)
class BundleIssue:
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class ParsedBundle:
    root: Path
    scope: str
    tenant_id: str | None
    revision: str
    concepts: dict[str, OkfConcept]


@dataclass(frozen=True)
class BundleValidation:
    valid: bool
    issues: tuple[BundleIssue, ...]
    bundle: ParsedBundle | None
