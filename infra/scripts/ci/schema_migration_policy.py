#!/usr/bin/env python3
"""Expand/contract schema policy: never silent destroy of durable tables.

UP sections may ADD tables/columns. DROP/TRUNCATE of durable names in UP is
forbidden. DOWN sections may drop what that file created.
"""

from __future__ import annotations

import re
from pathlib import Path

DURABLE = frozenset(
    {
        "audit_logs",
        "decisions",
        "cases",
        "tarka_outbox",
        "tarka_label_dlq",
        "normalized_labels",
        "decision_audit",
        "vendor_integration_audit",
        "inference_logs",
        "rule_approvals",
        "investigation_label_drafts",
        "leftover_promote_acks",
        "investigation_cases",
    }
)

_UP_MARK = re.compile(r"^--\s*=+\s*$", re.M)
_DROP = re.compile(
    r"\b(?:DROP\s+TABLE|DROP\s+COLUMN|TRUNCATE)\s+(?:IF\s+EXISTS\s+)?(?:\w+\.)?(\w+)",
    re.I,
)


def up_sql(text: str) -> str:
    """Return the UP half when `-- UP` / `-- DOWN` markers exist; else full text."""
    up_at = re.search(r"^--\s*=+\s*\n--\s*UP\b", text, re.I | re.M)
    down_at = re.search(r"^--\s*=+\s*\n--\s*DOWN\b", text, re.I | re.M)
    if up_at and down_at and down_at.start() > up_at.start():
        return text[up_at.start() : down_at.start()]
    # Single-block files without DOWN: treat entire file as UP.
    if re.search(r"^--\s*DOWN\b", text, re.I | re.M):
        return text[: re.search(r"^--\s*DOWN\b", text, re.I | re.M).start()]
    return text


def forbidden_up_drops(sql: str) -> list[str]:
    hits: list[str] = []
    for name in _DROP.findall(up_sql(sql)):
        if name.lower() in DURABLE:
            hits.append(name.lower())
    return hits


def scan_repo_migrations(root: Path) -> list[str]:
    errors: list[str] = []
    for rel in (
        "migrations",
        "infra/deploy/initdb",
    ):
        folder = root / rel
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.sql")):
            text = path.read_text(encoding="utf-8")
            drops = forbidden_up_drops(text)
            if drops:
                errors.append(f"{path.relative_to(root)}: UP drops durable {drops}")
    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[3]
    errors = scan_repo_migrations(root)
    if errors:
        print("schema migration policy failed:")
        for line in errors:
            print(f"  {line}")
        return 1
    print("schema migration policy: UP sections do not drop durable tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
