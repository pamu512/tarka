"""Integration ingress for KYC webhooks and adapters."""

# Expose `integration_ingress.main` so unittest.mock.patch("integration_ingress.main.…") resolves.
from . import main  # noqa: F401
