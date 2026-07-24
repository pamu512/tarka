"""Content-addressed rule pack identity (hash of canonical JSON, not filenames)."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any


_VOLATILE_PACK_KEYS = frozenset({"_source_file", "_loaded_at", "_runtime"})


def canonical_rule_pack_for_hash(pack: dict[str, Any]) -> dict[str, Any]:
    """Return a pack dict suitable for stable hashing (drops runtime-only keys)."""
    return {k: v for k, v in pack.items() if k not in _VOLATILE_PACK_KEYS}


def rule_pack_content_sha256(rule_pack: dict[str, Any]) -> str:
    raw = json.dumps(
        canonical_rule_pack_for_hash(rule_pack),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def packs_content_sha256(packs: list[dict[str, Any]]) -> str:
    """Hash an ordered list of packs; order is normalized by content hash then name."""
    digests = sorted(rule_pack_content_sha256(p) for p in packs if isinstance(p, dict))
    joined = ",".join(digests)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest() if joined else ""


def contributing_packs_content_sha256(
    packs: list[dict[str, Any]],
    contributing_files: list[str],
) -> str:
    wanted = {str(x).strip() for x in contributing_files if str(x).strip()}
    if not wanted:
        return packs_content_sha256(packs)
    selected = [
        p
        for p in packs
        if isinstance(p, dict) and str(p.get("_source_file") or "").strip() in wanted
    ]
    return packs_content_sha256(selected or packs)


def engine_build_identity() -> dict[str, str]:
    return {
        "git_sha": (
            os.environ.get("GIT_SHA") or os.environ.get("COMMIT_SHA") or ""
        ).strip(),
        "json_rules_engine": (
            os.environ.get("TARKA_JSON_RULES_ENGINE") or "auto"
        ).strip(),
        "rule_engine_wheel": (
            os.environ.get("TARKA_RULE_ENGINE_BUILD_ID") or ""
        ).strip(),
    }
