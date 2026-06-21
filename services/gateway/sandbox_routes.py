"""PLG sandbox routing metadata for API gateways.

The canonical ``POST /v1/sandbox/bootstrap`` handler is mounted on the Decision API
(``decision_api.sandbox_bootstrap``). Gateways should forward to that service or
import ``router`` only when colocating the decision app in-process.

This module exposes stable path constants and template data from ``tarka_core``
without depending on the Decision API package.
"""

from __future__ import annotations

from typing import Final

from tarka_core.templates import (
    INDUSTRY_RULE_TEMPLATE_ASTS,
    INDUSTRY_TEMPLATE_KEYS,
    list_industry_template_items,
)

SANDBOX_BOOTSTRAP_PATH: Final[str] = "/v1/sandbox/bootstrap"

__all__ = [
    "INDUSTRY_RULE_TEMPLATE_ASTS",
    "INDUSTRY_TEMPLATE_KEYS",
    "SANDBOX_BOOTSTRAP_PATH",
    "list_industry_template_items",
]
