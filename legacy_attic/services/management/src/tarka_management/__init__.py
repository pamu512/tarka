"""Tarka management-plane primitives (immutable rule registry)."""

from tarka_management.exceptions import DuplicateRuleVersionError, RuleRegistryError
from tarka_management.models import Base, RuleVersion
from tarka_management.registry import RuleRegistry

__all__ = [
    "Base",
    "DuplicateRuleVersionError",
    "RuleRegistry",
    "RuleRegistryError",
    "RuleVersion",
]
