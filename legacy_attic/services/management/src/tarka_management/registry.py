"""Append-only rule storage with SHA-256 content addressing and temporal replay."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tarka_management.exceptions import DuplicateRuleVersionError
from tarka_management.models import RuleVersion

logger = logging.getLogger(__name__)


class RuleRegistry:
    """Immutable rule versions indexed by name + SHA-256(rule_body UTF-8).

    * No rule row is ever overwritten in place for ``rule_body`` / ``content_hash`` / ``valid_from``.
    * Publishing a new revision closes the prior open interval by setting ``valid_to`` on the
      previously-active row (metadata-only update allowed by the PostgreSQL trigger in ``schema/``).
    """

    @staticmethod
    def content_hash(rule_body: str) -> str:
        """Lowercase hex SHA-256 of ``rule_body`` encoded as UTF-8 (matches ``tarka-core`` CAS)."""
        return hashlib.sha256(rule_body.encode("utf-8")).hexdigest()

    @staticmethod
    def _require_aware(dt: datetime) -> None:
        if dt.tzinfo is None:
            raise ValueError("datetime must be timezone-aware (use UTC for forensic timestamps)")

    def publish_new_version(
        self,
        session: Session,
        rule_name: str,
        rule_body: str,
        *,
        effective_at: datetime | None = None,
    ) -> RuleVersion:
        """Append a new immutable version and activate it at ``effective_at`` (default: now UTC).

        Raises:
            DuplicateRuleVersionError: same ``rule_name`` already has this exact ``content_hash``.
            ValueError: naive ``effective_at``.
        """
        effective_at = effective_at or datetime.now(timezone.utc)
        self._require_aware(effective_at)
        digest = self.content_hash(rule_body)

        prior_open = session.scalar(
            select(RuleVersion)
            .where(RuleVersion.rule_name == rule_name)
            .where(RuleVersion.valid_to.is_(None))
            .limit(1)
        )
        if prior_open is not None:
            prior_open.valid_to = effective_at

        row = RuleVersion(
            rule_name=rule_name,
            content_hash=digest,
            rule_body=rule_body,
            valid_from=effective_at,
            valid_to=None,
        )
        session.add(row)
        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            logger.warning(
                "rule registry rejected duplicate immutable version",
                extra={
                    "event": "DuplicateRuleVersion",
                    "rule_name": rule_name,
                    "content_hash": digest,
                },
            )
            raise DuplicateRuleVersionError(rule_name, digest) from exc

        return row

    def get_active_version(
        self,
        session: Session,
        rule_name: str,
        timestamp: datetime,
    ) -> RuleVersion | None:
        """Return the rule revision active at ``timestamp`` using half-open ``[valid_from, valid_to)``.

        ``valid_to`` is exclusive; ``NULL`` means still active. Returns ``None`` if no version covers
        ``timestamp`` (before first publish or gap — gaps should not occur with this registry).
        """
        self._require_aware(timestamp)
        stmt = (
            select(RuleVersion)
            .where(RuleVersion.rule_name == rule_name)
            .where(RuleVersion.valid_from <= timestamp)
            .where(
                or_(
                    RuleVersion.valid_to.is_(None),
                    timestamp < RuleVersion.valid_to,
                )
            )
            .order_by(RuleVersion.valid_from.desc())
            .limit(1)
        )
        return session.scalar(stmt)
