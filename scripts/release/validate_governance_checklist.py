#!/usr/bin/env python3
"""Validate infra/deploy/release/governance-checklist.yaml structure and doc linkage (Q1-E06)."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - CI installs pyyaml in lint job
    yaml = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CHECKLIST = ROOT / "deploy" / "release" / "governance-checklist.yaml"
OWNER_RE = re.compile(r"^[a-z][a-z0-9-]{1,48}$")
REQUIRED_ITEM_KEYS = ("id", "title", "owner", "section", "ci_required")


def _load_yaml(path: Path) -> dict:
    if yaml is None:
        print("FAIL: PyYAML is required (pip install pyyaml)", file=sys.stderr)
        raise SystemExit(2)
    if not path.is_file():
        print(f"FAIL: checklist not found: {path}", file=sys.stderr)
        raise SystemExit(1)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        print("FAIL: checklist root must be a mapping", file=sys.stderr)
        raise SystemExit(1)
    return data


def validate(data: dict, repo_root: Path) -> list[str]:
    errors: list[str] = []

    version = data.get("version")
    if not isinstance(version, str) or not version.strip():
        errors.append("missing or empty top-level 'version'")

    doc_rel = data.get("documentation")
    if not isinstance(doc_rel, str) or not doc_rel.strip():
        errors.append("missing or empty top-level 'documentation' path")
    else:
        doc_path = repo_root / doc_rel
        if not doc_path.is_file():
            errors.append(f"documentation file not found: {doc_rel}")

    owners = data.get("owners_registry")
    if not isinstance(owners, dict) or not owners:
        errors.append("owners_registry must be a non-empty mapping")
        known_owners: set[str] = set()
    else:
        known_owners = set()
        for key, label in owners.items():
            if not isinstance(key, str) or not OWNER_RE.match(key):
                errors.append(f"owners_registry key invalid: {key!r}")
            elif not isinstance(label, str) or not label.strip():
                errors.append(f"owners_registry label missing for {key!r}")
            else:
                known_owners.add(key)

    items = data.get("items")
    if not isinstance(items, list) or not items:
        errors.append("items must be a non-empty list")
        return errors

    seen_ids: set[str] = set()
    ci_required_count = 0

    for idx, item in enumerate(items):
        prefix = f"items[{idx}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be a mapping")
            continue

        for key in REQUIRED_ITEM_KEYS:
            if key not in item:
                errors.append(f"{prefix} missing required key '{key}'")

        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id.strip():
            errors.append(f"{prefix} id must be a non-empty string")
        elif item_id in seen_ids:
            errors.append(f"duplicate item id: {item_id}")
        else:
            seen_ids.add(item_id)

        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            errors.append(f"{prefix} title must be a non-empty string")

        owner = item.get("owner")
        if not isinstance(owner, str) or not OWNER_RE.match(owner):
            errors.append(f"{prefix} owner must match {OWNER_RE.pattern}: {owner!r}")
        elif known_owners and owner not in known_owners:
            errors.append(f"{prefix} owner {owner!r} not listed in owners_registry")

        section = item.get("section")
        if not isinstance(section, str) or not section.strip():
            errors.append(f"{prefix} section must be a non-empty string")

        ci_required = item.get("ci_required")
        if not isinstance(ci_required, bool):
            errors.append(f"{prefix} ci_required must be a boolean")
        elif ci_required:
            ci_required_count += 1

    if ci_required_count < 5:
        errors.append(f"expected at least 5 ci_required items, found {ci_required_count}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--checklist", type=Path, default=DEFAULT_CHECKLIST)
    args = parser.parse_args()

    checklist_path = args.checklist if args.checklist.is_absolute() else args.repo_root / args.checklist
    data = _load_yaml(checklist_path)
    errors = validate(data, args.repo_root)

    if errors:
        print("FAIL: governance checklist validation errors:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    item_count = len(data.get("items", []))
    owner_count = len(data.get("owners_registry", {}))
    print(
        f"OK: governance checklist valid ({item_count} items, {owner_count} owners) "
        f"-> {data.get('documentation')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
