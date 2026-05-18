"""Load and deploy versioned rules from ``fraud_rules`` (append-only) with ``engine_rules`` fallback."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def rules_database_url() -> str | None:
    import os

    raw = (
        os.environ.get("RULE_ENGINE_DATABASE_URL")
        or os.environ.get("SHADOW_DATABASE_URL", "").strip()
        or os.environ.get("TARKA_AUDIT_DATABASE_URL", "").strip()
    )
    if not raw or ":memory:" in raw:
        return None
    u = raw.strip()
    if u.startswith("sqlite+aiosqlite"):
        return u.replace("sqlite+aiosqlite", "sqlite+pysqlite", 1)
    if u.startswith("postgresql+asyncpg"):
        return u.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    if u.startswith("postgres+asyncpg"):
        return u.replace("postgres+asyncpg", "postgresql+psycopg", 1)
    return u


def _ensure_fraud_rules_table(engine: Engine) -> None:
    from tarka_shared.fraud_rules import FraudRulesVersion

    FraudRulesVersion.__table__.create(bind=engine, checkfirst=True)


def _rules_from_payload(payload: Any) -> list[Any]:
    from rule_engine.ast_schemas import Rule

    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, list):
        return []
    rules: list[Rule] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            rules.append(Rule.model_validate(item))
        except Exception:
            logger.exception("rule_engine_skip_invalid_rule_in_fraud_rules_payload")
    return rules


def load_rules_from_db(engine: Engine) -> tuple[Any, ...] | None:
    """
    Prefer the active row in ``fraud_rules`` (including an intentionally empty payload).

    If no active ``fraud_rules`` row exists, fall back to legacy ``engine_rules`` rows.

    Returns ``None`` when neither source yields rules (caller may use the in-process demo ruleset).
    """
    from rule_engine.ast_schemas import Rule

    _ensure_fraud_rules_table(engine)
    from tarka_shared.fraud_rules import FraudRulesVersion

    with Session(engine, expire_on_commit=False) as session:
        row = session.scalars(
            select(FraudRulesVersion)
            .where(FraudRulesVersion.is_active.is_(True))
            .order_by(FraudRulesVersion.version.desc())
            .limit(1),
        ).first()
    if row is not None:
        rules = _rules_from_payload(row.rules_payload)
        rules.sort(key=lambda r: r.priority)
        return tuple(rules)

    with engine.connect() as conn:
        try:
            result = conn.execute(text("SELECT definition FROM engine_rules"))
            rows = result.fetchall()
        except Exception:
            logger.exception("rule_engine_failed_to_read_engine_rules")
            return None

    if not rows:
        return None

    out: list[Rule] = []
    for (definition,) in rows:
        d: Any = definition
        if isinstance(d, str):
            d = json.loads(d)
        if not isinstance(d, dict):
            continue
        try:
            out.append(Rule.model_validate(d))
        except Exception:
            logger.exception("rule_engine_skip_invalid_rule_definition")
    if not out:
        return None
    out.sort(key=lambda r: r.priority)
    return tuple(out)


def _ast_payload_hash(payload: list[dict[str, Any]]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def list_fraud_rules_versions(engine: Engine) -> list[dict[str, Any]]:
    """Return immutable ``fraud_rules`` rows newest-first (for version control UI)."""
    _ensure_fraud_rules_table(engine)
    from tarka_shared.fraud_rules import FraudRulesVersion

    with Session(engine, expire_on_commit=False) as session:
        rows = session.scalars(
            select(FraudRulesVersion).order_by(FraudRulesVersion.version.desc()),
        ).all()
    out: list[dict[str, Any]] = []
    for row in rows:
        payload = row.rules_payload if isinstance(row.rules_payload, list) else []
        created = row.created_at
        if isinstance(created, datetime):
            created_at = created.isoformat()
        else:
            created_at = str(created) if created is not None else None
        out.append(
            {
                "version": int(row.version),
                "is_active": bool(row.is_active),
                "rule_count": len(payload),
                "created_at": created_at,
                "ast_hash": _ast_payload_hash(payload),
            },
        )
    return out


def get_fraud_rules_version_payload(engine: Engine, version: int) -> dict[str, Any] | None:
    """Return one version row including ``rules_payload`` for AST inspection."""
    _ensure_fraud_rules_table(engine)
    from tarka_shared.fraud_rules import FraudRulesVersion

    with Session(engine, expire_on_commit=False) as session:
        row = session.scalar(
            select(FraudRulesVersion).where(FraudRulesVersion.version == int(version)),
        )
    if row is None:
        return None
    payload = row.rules_payload if isinstance(row.rules_payload, list) else []
    created = row.created_at
    created_at = created.isoformat() if isinstance(created, datetime) else None
    return {
        "version": int(row.version),
        "is_active": bool(row.is_active),
        "rule_count": len(payload),
        "created_at": created_at,
        "ast_hash": _ast_payload_hash(payload),
        "rules_payload": payload,
    }


def activate_fraud_rules_version(engine: Engine, version: int) -> int:
    """
    Point the active ruleset at an existing ``fraud_rules`` row (rollback).

    Does not mutate ``rules_payload`` on any row — only toggles ``is_active``.
    """
    from tarka_shared.fraud_rules import FraudRulesVersion

    target = int(version)
    _ensure_fraud_rules_table(engine)
    with Session(engine, expire_on_commit=False) as session:
        with session.begin():
            row = session.scalar(
                select(FraudRulesVersion).where(FraudRulesVersion.version == target),
            )
            if row is None:
                raise LookupError(f"fraud_rules version {target} not found")
            session.execute(update(FraudRulesVersion).values(is_active=False))
            row.is_active = True
    return target


def deploy_new_rules_version(engine: Engine, rules: Sequence[Any]) -> int:
    """
    Append a new ``fraud_rules`` row (next ``version``), mark it active, deactivate others.

    Never updates existing rows' ``rules_payload`` (immutable history).
    """
    from tarka_shared.fraud_rules import FraudRulesVersion

    from rule_engine.ast_schemas import Rule

    validated: list[Rule] = [r if isinstance(r, Rule) else Rule.model_validate(r) for r in rules]
    payload = [r.model_dump(mode="json") for r in validated]

    _ensure_fraud_rules_table(engine)

    with Session(engine, expire_on_commit=False) as session:
        with session.begin():
            session.execute(update(FraudRulesVersion).values(is_active=False))
            current_max = session.scalar(select(func.max(FraudRulesVersion.version)))
            next_v = (int(current_max) if current_max is not None else 0) + 1
            session.add(FraudRulesVersion(version=next_v, is_active=True, rules_payload=payload))
    return next_v


def open_rules_engine() -> Engine | None:
    url = rules_database_url()
    if not url:
        return None
    return create_engine(url, future=True)
