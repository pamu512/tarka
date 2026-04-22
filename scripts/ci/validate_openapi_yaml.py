#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path

"""Validate OpenAPI contracts with YAML + semantic OAS checks.

Run from repo root after:
  pip install pyyaml openapi-spec-validator
"""
try:
    import yaml  # type: ignore[import-untyped]
except ImportError:
    print("Install PyYAML: pip install pyyaml", file=sys.stderr)
    raise SystemExit(2) from None

try:
    from openapi_spec_validator import validate  # type: ignore[import-untyped]
except ImportError:
    print("Install OpenAPI validator: pip install openapi-spec-validator", file=sys.stderr)
    raise SystemExit(2) from None


def main() -> int:
    root = Path(__file__).resolve().parents[2] / "contracts" / "openapi"
    if not root.is_dir():
        print(f"Missing directory: {root}", file=sys.stderr)
        return 2
    files = sorted(root.glob("*.yaml"))
    if not files:
        print(f"No *.yaml under {root}", file=sys.stderr)
        return 2
    failed = 0
    for p in files:
        try:
            spec = yaml.safe_load(p.read_text(encoding="utf-8"))
            if not isinstance(spec, dict):
                raise TypeError("root must be a mapping")
            if "openapi" not in spec:
                raise KeyError("missing openapi field")
            validate(spec)
        except Exception as exc:
            print(f"FAIL {p.relative_to(root.parents[1])}: {exc}", file=sys.stderr)
            failed += 1
    if failed:
        return 1
    print(f"OK: {len(files)} OpenAPI YAML files under {root.relative_to(root.parents[1])}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
