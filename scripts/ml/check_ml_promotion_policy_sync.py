#!/usr/bin/env python3
from __future__ import annotations
import json
import sys
from pathlib import Path

"""Ensure ml_promotion_policy_v1.json and .yaml parse to the same object (OSS #52)."""
_REPO = Path(__file__).resolve().parents[2]
_JSON = _REPO / "services" / "ml-scoring" / "rules" / "ml_promotion_policy_v1.json"
_YAML = _REPO / "services" / "ml-scoring" / "rules" / "ml_promotion_policy_v1.yaml"


def main() -> int:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        print("PyYAML is required: pip install pyyaml", file=sys.stderr)
        return 1
    if not _JSON.is_file() or not _YAML.is_file():
        print("policy files missing", file=sys.stderr)
        return 1
    jdoc = json.loads(_JSON.read_text(encoding="utf-8"))
    ydoc = yaml.safe_load(_YAML.read_text(encoding="utf-8"))
    if jdoc != ydoc:
        print("ml_promotion_policy_v1.json and ml_promotion_policy_v1.yaml differ when parsed.", file=sys.stderr)
        print("Update one to match the other.", file=sys.stderr)
        return 1
    print("OK: ML promotion policy JSON and YAML are in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
