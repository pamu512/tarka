#!/usr/bin/env python3
"""Ensure typology_definitions_v1.json references only rule ids that exist in JSON rule packs.

Fails CI if typologies drift from shipped packs (OSS #34 contract).
"""

from __future__ import annotations

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


def _rule_ids_from_pack(data: dict) -> set[str]:
    out: set[str] = set()
    for r in data.get("rules") or []:
        rid = r.get("id")
        if rid:
            out.add(str(rid))
    for r in data.get("tag_rules") or []:
        rid = r.get("id")
        if rid:
            out.add(str(rid))
    return out


def collect_rule_ids(rules_dir: Path) -> set[str]:
    ids: set[str] = set()
    skip = frozenset({"typology_definitions_v1.json"})
    for f in sorted(rules_dir.glob("*.json")):
        if f.name in skip:
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            raise SystemExit(f"{f.name}: {e}") from e
        if not isinstance(data, dict) or data.get("version", 1) != 1:
            continue
        ids |= _rule_ids_from_pack(data)
    return ids


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--rules-path",
        default=os.environ.get("RULES_PATH", str(_DEC / "rules")),
        help="Directory containing *.json rule packs and typology_definitions_v1.json",
    )
    args = p.parse_args()
    rules_dir = Path(args.rules_path)
    typ_path = rules_dir / "typology_definitions_v1.json"
    if not typ_path.is_file():
        print(f"OK: no {typ_path.name} (optional)", file=sys.stderr)
        return 0
    try:
        typ_data = json.loads(typ_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"{typ_path.name}: invalid JSON ({e})", file=sys.stderr)
        return 1
    rule_ids = collect_rule_ids(rules_dir)
    errors: list[str] = []
    for spec in typ_data.get("typologies") or []:
        tid = spec.get("id") or "?"
        for mid in spec.get("member_rule_ids") or []:
            ms = str(mid)
            if ms not in rule_ids:
                errors.append(f"typology {tid!r} references unknown member_rule_id {ms!r}")
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        print(
            "\nFix: add the rule id to a pack under rules_path, or remove it from typology_definitions_v1.json.",
            file=sys.stderr,
        )
        return 1
    print(f"OK: typology member_rule_ids resolve against {len(rule_ids)} rule/tag_rule ids in {rules_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
