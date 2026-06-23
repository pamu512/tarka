"""Domain errors for the rule registry."""

from __future__ import annotations


class RuleRegistryError(RuntimeError):
    """Base class for rule registry failures."""


class DuplicateRuleVersionError(RuleRegistryError):
    """Publishing failed because this rule_name already has a version with the same content hash."""

    def __init__(self, rule_name: str, content_hash: str) -> None:
        self.rule_name = rule_name
        self.content_hash = content_hash
        super().__init__(
            f"immutable duplicate: rule_name={rule_name!r} already has version with "
            f"content_hash={content_hash}"
        )
