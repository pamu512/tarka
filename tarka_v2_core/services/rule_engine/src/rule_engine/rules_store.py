"""Load and deploy versioned rules from ``fraud_rules`` (append-only) with ``engine_rules`` fallback."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
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
