"""Per-tenant custom schema configuration.

Each tenant may define additional entity types (node labels) and relationship
types beyond the built-in defaults.  Schemas are stored as JSON files in a
``schemas/`` directory adjacent to the service package root.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_SAFE_TENANT_ID = re.compile(r"^[A-Za-z0-9_-]{1,120}$")


def _norm_rel_token(rel: str) -> str:
    return str(rel).strip().upper().replace(" ", "_").replace("-", "_")

_SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "schemas"

_DEFAULT_ENTITY_TYPES = [
    "Person",
    "Account",
    "Device",
    "Place",
    "Payment",
    "Document",
    "Custom",
]
_DEFAULT_RELATIONSHIP_TYPES = [
    "USED",
    "SEEN_AT",
    "SHARED_WITH",
    "REFERRED",
    "KYC_VERIFIED_BY",
    "OWNS",
    "CUSTOM",
    "RELATED",
]


class TenantSchema:
    """Represents the allowed entity types and relationship types for a single tenant.

    Merges the built-in defaults with whatever the tenant has configured in its
    JSON file.
    """

    def __init__(
        self,
        tenant_id: str,
        entity_types: list[str] | None = None,
        relationship_types: list[str] | None = None,
        extra: dict[str, Any] | None = None,
        typed_edges: list[dict[str, Any]] | None = None,
        node_context_hints: dict[str, list[str]] | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.entity_types: list[str] = list(dict.fromkeys(_DEFAULT_ENTITY_TYPES + (entity_types or [])))
        self.relationship_types: list[str] = list(dict.fromkeys(_DEFAULT_RELATIONSHIP_TYPES + (relationship_types or [])))
        self.extra: dict[str, Any] = extra or {}
        self.typed_edges: list[dict[str, Any]] = list(typed_edges or [])
        self.node_context_hints: dict[str, list[str]] = dict(node_context_hints or {})

    def allows_label(self, label: str) -> bool:
        return label in self.entity_types

    def allows_relationship(self, rel: str) -> bool:
        return rel in self.relationship_types

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "entity_types": self.entity_types,
            "relationship_types": self.relationship_types,
            "typed_edges": self.typed_edges,
            "node_context_hints": self.node_context_hints,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TenantSchema:
        extra = dict(data.get("extra") or {})
        typed_edges = data.get("typed_edges")
        if typed_edges is None and "typed_edges" in extra:
            typed_edges = extra.pop("typed_edges", None)
        hints = data.get("node_context_hints")
        if hints is None and "node_context_hints" in extra:
            hints = extra.pop("node_context_hints", None)
        return cls(
            tenant_id=data.get("tenant_id", "default"),
            entity_types=data.get("entity_types"),
            relationship_types=data.get("relationship_types"),
            extra=extra or None,
            typed_edges=typed_edges if isinstance(typed_edges, list) else None,
            node_context_hints=hints if isinstance(hints, dict) else None,
        )


_cache: dict[str, TenantSchema] = {}


def _schema_path(tenant_id: str) -> Path:
    if not _SAFE_TENANT_ID.fullmatch(tenant_id):
        raise ValueError("invalid tenant_id")
    key = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()
    path = (_SCHEMAS_DIR / f"{key}.json").resolve()
    try:
        path.relative_to(_SCHEMAS_DIR.resolve())
    except ValueError as exc:
        raise ValueError("invalid tenant_id") from exc
    return path


def load_tenant_schema(tenant_id: str) -> TenantSchema:
    """Load a tenant schema from disk (with in-memory cache).

    Falls back to the ``default.json`` schema if the tenant-specific file
    does not exist, and falls back to built-in defaults if neither exists.
    """
    if tenant_id in _cache:
        return _cache[tenant_id]

    try:
        path = _schema_path(tenant_id)
    except ValueError:
        schema = TenantSchema(tenant_id=tenant_id)
        _cache[tenant_id] = schema
        return schema
    if not path.exists():
        path = _SCHEMAS_DIR / "default.json"

    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            schema = TenantSchema.from_dict({**data, "tenant_id": tenant_id})
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("failed to read schema %s: %s — using defaults", path, exc)
            schema = TenantSchema(tenant_id=tenant_id)
    else:
        schema = TenantSchema(tenant_id=tenant_id)

    _cache[tenant_id] = schema
    return schema


def save_tenant_schema(schema: TenantSchema) -> None:
    """Persist a tenant schema to disk and refresh the cache.

    Rejects any entity type or relationship type that isn't a safe Cypher
    identifier (alphanumeric + underscore, starts with a letter, max 64 chars).
    """
    bad = [t for t in schema.entity_types + schema.relationship_types if not _SAFE_IDENTIFIER.match(t)]
    if bad:
        raise ValueError(f"unsafe identifiers rejected: {bad}")
    for spec in schema.typed_edges:
        if not isinstance(spec, dict):
            raise ValueError("typed_edges entries must be objects")
        rel = str(spec.get("relationship", "")).strip()
        if rel and not _SAFE_IDENTIFIER.match(_norm_rel_token(rel)):
            raise ValueError(f"unsafe typed_edges.relationship rejected: {rel}")
        for key in ("from_entity_types", "to_entity_types"):
            for t in spec.get(key) or []:
                ts = str(t).strip()
                if ts and not _SAFE_IDENTIFIER.match(ts):
                    raise ValueError(f"unsafe typed_edges.{key} entry rejected: {t}")
    for nt, keys in schema.node_context_hints.items():
        if not _SAFE_IDENTIFIER.match(str(nt).strip()):
            raise ValueError(f"unsafe node_context_hints key rejected: {nt}")
        for k in keys:
            ks = str(k).strip()
            if ks and not _SAFE_IDENTIFIER.match(ks):
                raise ValueError(f"unsafe node_context_hints value rejected: {k}")

    _SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)
    path = _schema_path(schema.tenant_id)
    path.write_text(
        json.dumps(schema.to_dict(), indent=2),
        encoding="utf-8",
    )
    _cache[schema.tenant_id] = schema
    log.info("saved schema for tenant %s to %s", schema.tenant_id, path)


def invalidate_cache(tenant_id: str | None = None) -> None:
    """Drop cached schemas — all tenants or a specific one."""
    if tenant_id is None:
        _cache.clear()
    else:
        _cache.pop(tenant_id, None)


def get_allowed_labels(tenant_id: str) -> frozenset[str]:
    """Return the full set of allowed node labels for a tenant."""
    schema = load_tenant_schema(tenant_id)
    return frozenset(schema.entity_types)


def get_allowed_rels(tenant_id: str) -> frozenset[str]:
    """Return the full set of allowed relationship types for a tenant."""
    schema = load_tenant_schema(tenant_id)
    return frozenset(schema.relationship_types)
