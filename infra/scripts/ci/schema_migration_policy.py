#!/usr/bin/env python3
"""Expand/contract schema policy: never silent destroy of durable tables.

SQL: UP sections may ADD. DROP TABLE / ALTER TABLE … DROP COLUMN / TRUNCATE of
durable names in UP is forbidden. DOWN may drop what that file created.

Alembic: only ``upgrade()`` is scanned (``downgrade()`` may drop). Production
Postgres runs ``alembic upgrade head`` on core-api / case-api start.
"""

from __future__ import annotations

import ast
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

_DROP_TABLE = re.compile(
    r"\bDROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:\w+\.)?(\w+)",
    re.I,
)
_ALTER_DROP_COL = re.compile(
    r"\bALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:\w+\.)?(\w+)\s+DROP\s+COLUMN",
    re.I,
)
_TRUNCATE = re.compile(
    r"\bTRUNCATE\s+(?:TABLE\s+)?(?:\w+\.)?(\w+)",
    re.I,
)
_ALEMBIC_DROP = frozenset({"drop_table", "drop_column"})


def up_sql(text: str) -> str:
    """Return the UP half when `-- UP` / `-- DOWN` markers exist; else full text."""
    up_at = re.search(r"^--\s*=+\s*\n--\s*UP\b", text, re.I | re.M)
    down_at = re.search(r"^--\s*=+\s*\n--\s*DOWN\b", text, re.I | re.M)
    if up_at and down_at and down_at.start() > up_at.start():
        return text[up_at.start() : down_at.start()]
    down_only = re.search(r"^--\s*DOWN\b", text, re.I | re.M)
    if down_only:
        return text[: down_only.start()]
    return text


def forbidden_up_drops(sql: str) -> list[str]:
    blob = up_sql(sql)
    hits: list[str] = []
    for rx in (_DROP_TABLE, _ALTER_DROP_COL, _TRUNCATE):
        for name in rx.findall(blob):
            key = name.lower()
            if key in DURABLE and key not in hits:
                hits.append(key)
    return hits


def _first_str_arg(call: ast.Call) -> str | None:
    if not call.args:
        return None
    arg = call.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    return None


def alembic_upgrade_drops(text: str) -> list[str]:
    """Durable table names dropped or column-dropped inside ``upgrade()``."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    hits: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name != "upgrade":
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            func = child.func
            name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else func.id
                if isinstance(func, ast.Name)
                else ""
            )
            if name not in _ALEMBIC_DROP:
                continue
            table = _first_str_arg(child)
            if table and table.lower() in DURABLE and table.lower() not in hits:
                hits.append(table.lower())
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
            drops = forbidden_up_drops(path.read_text(encoding="utf-8"))
            if drops:
                errors.append(f"{path.relative_to(root)}: UP drops durable {drops}")
    for rel in (
        "services/decision-api/alembic/versions",
        "services/case-api/alembic/versions",
        "packages/shared-core/alembic/versions",
    ):
        folder = root / rel
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.py")):
            drops = alembic_upgrade_drops(path.read_text(encoding="utf-8"))
            if drops:
                errors.append(f"{path.relative_to(root)}: upgrade() drops durable {drops}")
    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[3]
    errors = scan_repo_migrations(root)
    if errors:
        print("schema migration policy failed:")
        for line in errors:
            print(f"  {line}")
        return 1
    print("schema migration policy: UP/upgrade() do not drop durable tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
