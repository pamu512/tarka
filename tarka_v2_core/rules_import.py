"""Import validated AST rules into ``engine_rules`` and hot-reload the rule-engine cache."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SHARED_ROOT = _REPO_ROOT / "tarka_v2_core" / "services" / "shared"
_RULE_ENGINE_SRC = _REPO_ROOT / "tarka_v2_core" / "services" / "rule_engine" / "src"
_INGESTOR_SRC = _REPO_ROOT / "tarka_v2_core" / "services" / "ingestor" / "src"

for _p in (_SHARED_ROOT, _RULE_ENGINE_SRC, _INGESTOR_SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


class ImportRulesError(RuntimeError):
    """Validation, DB, or reload failures for ``import-rules``."""


def _async_to_sync_database_url(url: str) -> str:
    u = url.strip()
    if u.startswith("sqlite+aiosqlite"):
        return u.replace("sqlite+aiosqlite", "sqlite+pysqlite", 1)
    if u.startswith("postgresql+asyncpg"):
        return u.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    if u.startswith("postgres+asyncpg"):
        return u.replace("postgres+asyncpg", "postgresql+psycopg", 1)
    return u


def _database_url() -> str:
    raw = (
        os.environ.get("TARKA_RULES_DATABASE_URL")
        or os.environ.get("SHADOW_DATABASE_URL", "").strip()
        or os.environ.get("TARKA_AUDIT_DATABASE_URL", "").strip()
    )
    if not raw:
        raise ImportRulesError(
            "Set SHADOW_DATABASE_URL (or TARKA_RULES_DATABASE_URL) to the same database used by "
            "the Shadow sidecar / rule-engine persistence (file SQLite or Postgres URL)."
        )
    if ":memory:" in raw:
        raise ImportRulesError(
            "In-memory SQLite cannot store imported rules; use a file path or Postgres URL."
        )
    return _async_to_sync_database_url(raw)


def _parse_rules_payload(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        if "rules" in raw:
            inner = raw["rules"]
            if not isinstance(inner, list):
                raise ImportRulesError('"rules" must be a JSON array')
            return [x for x in inner if isinstance(x, dict)]
        return [raw]
    raise ImportRulesError("JSON root must be an object, {rules: [...]}, or an array of rules")


def run_import_rules(
    filepath: Path,
    *,
    skip_reload: bool = False,
    rule_engine_base: str | None = None,
) -> tuple[int, str | None]:
    """
    Load JSON from ``filepath``, validate each object as :class:`rule_engine.ast_schemas.Rule`,
    upsert rows into ``engine_rules``, then ``POST /v1/rules/reload`` unless ``skip_reload``.

    Returns ``(rule_count, reload_error_or_none)``.
    """
    try:
        from rule_engine.ast_schemas import Rule
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from tarka_shared.engine_rules import EngineRule
    except ImportError as exc:
        raise ImportRulesError(
            "Missing dependencies for import-rules (need sqlalchemy and repo packages on PYTHONPATH)."
        ) from exc

    path = filepath.expanduser().resolve()
    if not path.is_file():
        raise ImportRulesError(f"Not a file: {path}")

    try:
        raw_json = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ImportRulesError(f"Invalid JSON in {path}: {exc}") from exc

    dicts = _parse_rules_payload(raw_json)
    if not dicts:
        raise ImportRulesError("No rule objects found in JSON")

    validated: list[Rule] = []
    for i, obj in enumerate(dicts):
        try:
            validated.append(Rule.model_validate(obj))
        except Exception as exc:
            raise ImportRulesError(f"Rule at index {i} failed validation: {exc}") from exc

    url = _database_url()
    engine = create_engine(url, future=True)

    try:
        from tarka_shared.database.session import Base

        with engine.begin() as conn:
            Base.metadata.create_all(conn, tables=[EngineRule.__table__])
    except Exception as exc:
        raise ImportRulesError(f"Failed to ensure engine_rules table: {exc}") from exc

    try:
        with Session(engine, expire_on_commit=False) as session:
            for rule in validated:
                session.merge(
                    EngineRule(
                        id=str(rule.id),
                        definition=rule.model_dump(mode="json"),
                    )
                )
            session.commit()
    except Exception as exc:
        raise ImportRulesError(f"Failed to write engine_rules: {exc}") from exc
    finally:
        engine.dispose()

    reload_err: str | None = None
    if not skip_reload and not os.environ.get("TARKA_SKIP_RULE_RELOAD"):
        base = (rule_engine_base or os.environ.get("RULE_ENGINE_URL", "http://127.0.0.1:8778")).strip().rstrip("/")
        reload_url = f"{base}/v1/rules/reload"
        try:
            with httpx.Client(timeout=30.0) as client:
                r = client.post(reload_url)
                r.raise_for_status()
        except Exception as exc:
            reload_err = f"{reload_url}: {exc}"

    return len(validated), reload_err
