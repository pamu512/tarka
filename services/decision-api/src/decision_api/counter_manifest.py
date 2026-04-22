from __future__ import annotations

"""Load and validate the v1 counter manifest (online/offline parity contract)."""


import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_MANIFEST_FILE = "counter_manifest_v1.json"


def _manifest_path() -> Path:
    return Path(__file__).resolve().parent / "data" / _MANIFEST_FILE


@lru_cache
def load_counter_manifest_v1() -> dict[str, Any]:
    """Return the bundled counter manifest (JSON)."""
    return json.loads(_manifest_path().read_text(encoding="utf-8"))


def manifest_version() -> str:
    m = load_counter_manifest_v1()
    return str(m.get("manifest_version", "0"))


def expected_feature_names() -> frozenset[str]:
    m = load_counter_manifest_v1()
    feats = m.get("feature_outputs") or []
    names = [str(x.get("name", "")).strip() for x in feats if isinstance(x, dict)]
    return frozenset(n for n in names if n)


def validate_feature_dict(features: dict[str, Any]) -> list[str]:
    """Return list of manifest feature names missing from *features* (empty if OK)."""
    expected = expected_feature_names()
    present = frozenset(features.keys())
    return sorted(expected - present)
