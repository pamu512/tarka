"""Field registry v1: seed names, validation, remap, and payload discover."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

REGISTRY_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
SOURCES = frozenset({"tarka_core", "sdk_tarka", "mapped_buyer", "enrichment", "new_feature"})

_seed_load_logged = False


def validate_registry_name(name: str) -> str:
    """Strip. Raise ValueError if empty, not REGISTRY_NAME_RE, or startswith tx_."""
    stripped = name.strip()
    if not stripped:
        raise ValueError("registry name must not be empty")
    if stripped.startswith("tx_"):
        raise ValueError(f"registry name must not start with tx_: {stripped!r}")
    if not REGISTRY_NAME_RE.fullmatch(stripped):
        raise ValueError(f"invalid registry name: {stripped!r}")
    return stripped


def _seed_path() -> Path:
    here = Path(__file__).resolve()
    for p in here.parents:
        cand = p / "services/decision-api/src/decision_api/data/field_registry_v1.json"
        if cand.is_file():
            return cand
        cand = p / "decision_api/data/field_registry_v1.json"
        if cand.is_file():
            return cand
    return here.parent / "decision_api/data/field_registry_v1.json"


def load_seed_rows() -> list[dict]:
    """Read field_registry_v1.json. Missing/invalid file → [] (log once)."""
    global _seed_load_logged
    path = _seed_path()
    if not path.is_file():
        if not _seed_load_logged:
            log.warning("field registry seed file missing: %s", path)
            _seed_load_logged = True
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        if not _seed_load_logged:
            log.warning("field registry seed file invalid: %s (%s)", path, exc)
            _seed_load_logged = True
        return []
    if not isinstance(raw, list):
        if not _seed_load_logged:
            log.warning("field registry seed file must be a JSON array: %s", path)
            _seed_load_logged = True
        return []
    rows: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not name:
            continue
        rows.append(
            {
                "name": str(name).strip(),
                "explanation": str(item.get("explanation") or "").strip(),
                "source": "tarka_core",
            }
        )
    return rows


def seed_names() -> frozenset[str]:
    return frozenset(r["name"] for r in load_seed_rows() if r.get("name"))


def merge_registry_rows(*, seed: list[dict], overlay: list[dict]) -> list[dict]:
    """By name: overlay wins. Do not invent names."""
    by_name: dict[str, dict] = {}
    for row in seed:
        if isinstance(row, dict) and row.get("name"):
            by_name[str(row["name"])] = dict(row)
    for row in overlay:
        if isinstance(row, dict) and row.get("name"):
            by_name[str(row["name"])] = dict(row)
    return list(by_name.values())


def apply_field_maps(payload: dict, maps: list[tuple[str, str]]) -> dict:
    """Copy payload. For (buyer_key, registry_name): if buyer_key in out and registry_name not in out, set it."""
    out = dict(payload)
    for buyer_key, registry_name in maps:
        if buyer_key not in out:
            continue
        if registry_name in out:
            continue
        value = out[buyer_key]
        if value == 0:
            continue
        out[registry_name] = value
    return out


def discover_payload(
    payload: dict,
    *,
    registry_names: set[str],
    maps: dict[str, str],
) -> dict:
    """already_named / mapped / candidates as spec JSON."""
    already_named: list[str] = []
    mapped: list[dict[str, str]] = []
    candidates: list[dict[str, str]] = []
    for buyer_key in payload:
        if buyer_key in registry_names:
            already_named.append(buyer_key)
        elif buyer_key in maps:
            mapped.append({"buyer_key": buyer_key, "registry_name": maps[buyer_key]})
        else:
            candidates.append({"buyer_key": buyer_key, "suggested_source": "new_feature"})
    return {
        "already_named": already_named,
        "mapped": mapped,
        "candidates": candidates,
    }
