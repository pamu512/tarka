"""Versioned policy-set identity: JSON packs + typology + challenge policies."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

log = logging.getLogger(__name__)

POLICY_SET_SCHEMA = "tarka.policy_set/v1"

_generation: int = 0
_cache: dict[str, Any] | None = None
_cache_generation: int = -1


def bump_policy_set_generation() -> None:
    """Invalidate cached policy-set identity after pack/typology/challenge reload."""
    global _generation, _cache, _cache_generation
    _generation += 1
    _cache = None
    _cache_generation = -1


def _sha256_canonical(obj: Any) -> str:
    raw = json.dumps(obj, sort_keys=True, default=str, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(raw).hexdigest()


def _pack_content_for_hash(pack: dict[str, Any]) -> dict[str, Any]:
    """Stable pack body for hashing (drop runtime-only keys)."""
    out = {k: v for k, v in pack.items() if not str(k).startswith("_")}
    return out


def _json_pack_rows() -> list[dict[str, Any]]:
    from decision_api.json_rules import get_active_packs_snapshot

    rows: list[dict[str, Any]] = []
    for pack in get_active_packs_snapshot():
        if not isinstance(pack, dict):
            continue
        file_name = str(pack.get("_source_file") or pack.get("name") or "pack")
        content = _pack_content_for_hash(pack)
        rows.append(
            {
                "file": file_name,
                "name": str(pack.get("name") or ""),
                "mode": str(pack.get("mode") or "active"),
                "rule_count": len(pack.get("rules") or [])
                if isinstance(pack.get("rules"), list)
                else 0,
                "sha256": _sha256_canonical(content),
            }
        )
    rows.sort(key=lambda r: r["file"])
    return rows


def _typology_component() -> dict[str, Any]:
    from decision_api.typology import load_typology_definitions

    data = load_typology_definitions()
    typologies = data.get("typologies") if isinstance(data, dict) else None
    count = len(typologies) if isinstance(typologies, list) else 0
    return {
        "file": "typology_definitions_v1.json",
        "version": int(data.get("version", 1)) if isinstance(data, dict) else 1,
        "typology_count": count,
        "sha256": _sha256_canonical(data if isinstance(data, dict) else {}),
    }


def _challenge_rows() -> list[dict[str, Any]]:
    from decision_api.challenge_policy import iter_loaded_policies

    rows: list[dict[str, Any]] = []
    for pid, policy in iter_loaded_policies():
        rows.append(
            {
                "policy_id": pid,
                "version": int(policy.get("version", 1)),
                "sha256": _sha256_canonical(policy),
            }
        )
    rows.sort(key=lambda r: r["policy_id"])
    return rows


def build_policy_set_manifest() -> dict[str, Any]:
    """Compute the current policy-set manifest from in-memory loaded policy artifacts."""
    json_packs = _json_pack_rows()
    typology = _typology_component()
    challenge = _challenge_rows()
    identity = {
        "json_packs": [{"file": r["file"], "sha256": r["sha256"]} for r in json_packs],
        "typology": {"file": typology["file"], "sha256": typology["sha256"]},
        "challenge_policies": [
            {"policy_id": r["policy_id"], "sha256": r["sha256"]} for r in challenge
        ],
    }
    policy_set_id = _sha256_canonical(identity)
    return {
        "schema": POLICY_SET_SCHEMA,
        "policy_set_id": policy_set_id,
        "components": {
            "json_packs": json_packs,
            "typology": typology,
            "challenge_policies": challenge,
        },
        "counts": {
            "json_packs": len(json_packs),
            "typologies": int(typology.get("typology_count") or 0),
            "challenge_policies": len(challenge),
        },
    }


def get_policy_set_manifest(*, force: bool = False) -> dict[str, Any]:
    """Cached posture snapshot; recomputed when generation bumps or ``force``."""
    global _cache, _cache_generation
    if not force and _cache is not None and _cache_generation == _generation:
        return dict(_cache)
    manifest = build_policy_set_manifest()
    _cache = manifest
    _cache_generation = _generation
    return dict(manifest)


def current_policy_set_id() -> str:
    """Stable policy-set fingerprint for evaluate responses / audit."""
    return str(get_policy_set_manifest().get("policy_set_id") or "")
