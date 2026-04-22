#!/usr/bin/env python3
from __future__ import annotations

"""Validate JSON rule packs under services/decision-api/rules (or RULES_PATH).

Exit 0 if all packs parse and pass structural validation (same checks as rule_api).
Used by CI for policy-as-code gate.
"""


import argparse
import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_DEC = _REPO / "services" / "decision-api"
_SRC = _DEC / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--rules-path",
        default=os.environ.get("RULES_PATH", str(_DEC / "rules")),
        help="Directory containing *.json rule packs",
    )
    args = p.parse_args()
    rules_dir = Path(args.rules_path)
    if not rules_dir.is_dir():
        print(f"rules path not found: {rules_dir}", file=sys.stderr)
        return 1

    from decision_api.rule_pack_validation import validate_rule_pack

    errors: list[str] = []
    skip_names = frozenset({"typology_definitions_v1.json", "typology_predicate_registry_v1.json"})
    for f in sorted(rules_dir.glob("*.json")):
        if f.name in skip_names:
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            errors.append(f"{f.name}: invalid JSON ({e})")
            continue
        if not isinstance(data, dict):
            errors.append(f"{f.name}: root must be object")
            continue
        ver = data.get("version", 1)
        if ver != 1:
            errors.append(f"{f.name}: unsupported version {ver!r} (expected 1)")
            continue
        errs = validate_rule_pack(data)
        for e in errs:
            errors.append(f"{f.name}: {e}")

    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return 1
    print(f"OK: validated rule packs in {rules_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
