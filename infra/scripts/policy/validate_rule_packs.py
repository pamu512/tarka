#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

"""Validate JSON rule packs under decision-api rules (or RULES_PATH).

Also validates v2 Hetu rule-engine AST packs under services/rule_engine/.

Exit 0 if all packs parse and pass structural validation (same checks as rule_api).
Used by CI for policy-as-code gate.
"""
_REPO = Path(__file__).resolve().parents[3]
_DEC = _REPO / "services" / "decision-api"
_V2_RULE_ENGINE = _REPO / "services" / "rule_engine"
_SRC = _DEC / "src"
_SHARED_CORE = _REPO / "packages" / "shared-core"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
if str(_SHARED_CORE) not in sys.path:
    sys.path.insert(0, str(_SHARED_CORE))


def _validate_v1_packs(rules_dir: Path) -> list[str]:
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
    return errors


def _validate_v2_packs(v2_root: Path) -> list[str]:
    services_root = v2_root.parent
    for entry in (services_root, v2_root):
        s = str(entry)
        if s not in sys.path:
            sys.path.insert(0, s)

    from tarka_shared.ast_schemas import Rule

    errors: list[str] = []
    pack_dirs = [
        v2_root / "rule_packs",
        v2_root / "tests" / "fixtures",
    ]
    seen: set[Path] = set()
    for pack_dir in pack_dirs:
        if not pack_dir.is_dir():
            continue
        for f in sorted(pack_dir.rglob("*.json")):
            if f in seen:
                continue
            seen.add(f)
            rel = f.relative_to(v2_root)
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                errors.append(f"v2 {rel}: invalid JSON ({e})")
                continue

            rules_payload: list[object]
            if isinstance(data, list):
                rules_payload = data
            elif isinstance(data, dict) and isinstance(data.get("rules"), list):
                rules_payload = data["rules"]
            else:
                errors.append(f"v2 {rel}: root must be {{\"rules\": [...]}} or a list")
                continue

            if not rules_payload:
                errors.append(f"v2 {rel}: rules list is empty")
                continue

            for idx, item in enumerate(rules_payload):
                if not isinstance(item, dict):
                    errors.append(f"v2 {rel}: rules[{idx}] must be object")
                    continue
                try:
                    Rule.model_validate(item)
                except Exception as exc:
                    errors.append(f"v2 {rel}: rules[{idx}]: {exc}")
    return errors


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--rules-path",
        default=os.environ.get("RULES_PATH", str(_DEC / "rules")),
        help="Directory containing legacy v1 *.json rule packs",
    )
    p.add_argument(
        "--v2-rule-engine-path",
        default=str(_V2_RULE_ENGINE),
        help="Root of v2 rule-engine service (scans rule_packs/ and tests/fixtures/)",
    )
    p.add_argument(
        "--skip-v2",
        action="store_true",
        help="Validate legacy v1 packs only",
    )
    args = p.parse_args()
    rules_dir = Path(args.rules_path)
    if not rules_dir.is_dir():
        print(f"rules path not found: {rules_dir}", file=sys.stderr)
        return 1

    errors = _validate_v1_packs(rules_dir)
    v2_root = Path(args.v2_rule_engine_path)
    if not args.skip_v2:
        if not v2_root.is_dir():
            errors.append(f"v2 rule-engine path not found: {v2_root}")
        else:
            errors.extend(_validate_v2_packs(v2_root))

    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return 1

    msg = f"OK: validated v1 rule packs in {rules_dir}"
    if not args.skip_v2 and v2_root.is_dir():
        msg += f"; v2 AST packs under {v2_root}"
    print(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
