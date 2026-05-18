#!/usr/bin/env python3
"""
Gate check: ``BaseLLMProvider`` subclasses without ``generate_decision`` must not instantiate.

Expects ``TypeError`` from ABC machinery (missing abstract method).
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "tarka_v2_core" / "services" / "shadow_agent" / "src"
sys.path.insert(0, str(_SRC))

from shadow_agent.providers.base import BaseLLMProvider  # noqa: E402


class _DummyIncompleteProvider(BaseLLMProvider):
    """Deliberately omits ``generate_decision`` to prove the ABC gate."""

    pass


def main() -> int:
    try:
        _DummyIncompleteProvider()
    except TypeError as exc:
        msg = str(exc).lower()
        if "abstract" in msg and "generate_decision" in msg:
            print(f"gate_ok: {exc}")
            return 0
        print(f"gate_partial: TypeError but unexpected message: {exc!r}", file=sys.stderr)
        return 1

    print(
        "gate_fail: expected TypeError when instantiating incomplete BaseLLMProvider",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
