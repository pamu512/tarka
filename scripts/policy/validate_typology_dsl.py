#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

"""OSS #46 — validate typology_definitions + predicate registry pins and predicate_ref ids."""
_REPO = Path(__file__).resolve().parents[2]
_DEC = _REPO / "services" / "decision-api"
_RULES = _DEC / "rules"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--rules-path", default=os.environ.get("RULES_PATH", str(_RULES)))
    args = p.parse_args()
    rules_dir = Path(args.rules_path)
    typ_path = rules_dir / "typology_definitions_v1.json"
    reg_path = rules_dir / "typology_predicate_registry_v1.json"
    if not typ_path.is_file():
        print(f"OK: no {typ_path.name}")
        return 0
    try:
        typ = json.loads(typ_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"{typ_path}: {e}", file=sys.stderr)
        return 1
    reg: dict = {}
    if reg_path.is_file():
        try:
            reg = json.loads(reg_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"{reg_path}: {e}", file=sys.stderr)
            return 1
    reg_ids = {str(x.get("id")) for x in (reg.get("predicates") or []) if x.get("id")}
    reg_ver = int(reg.get("version") or 0)
    pin = typ.get("predicate_registry_pin")
    pin_int = int(pin) if pin is not None else reg_ver
    errors: list[str] = []
    if reg and reg_ver != pin_int:
        errors.append(f"typology_definitions predicate_registry_pin ({pin_int}) != registry version ({reg_ver}) — bump pin or registry together")
    for spec in typ.get("typologies") or []:
        tid = spec.get("id") or "?"
        for pred in spec.get("feature_predicates") or []:
            if not isinstance(pred, dict):
                continue
            ref = str(pred.get("predicate_ref") or "").strip()
            if ref:
                if ref not in reg_ids:
                    errors.append(f"typology {tid}: unknown predicate_ref {ref!r}")
            else:
                if not pred.get("field"):
                    errors.append(f"typology {tid}: feature_predicate must have predicate_ref or inline field")
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return 1
    print(f"OK: typology DSL + predicate registry in {rules_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
