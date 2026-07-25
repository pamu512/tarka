"""Integration ingress for KYC webhooks and adapters."""

from typing import Any


def __getattr__(name: str) -> Any:
    # Lazy: keep subpackage imports (e.g. vendor_finops) free of FastAPI/app deps.
    # unittest.mock.patch("integration_ingress.main.…") still resolves via this.
    if name == "main":
        from . import main as _main

        return _main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
