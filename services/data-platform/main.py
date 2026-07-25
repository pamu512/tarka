"""Compatibility listener on :8014 for Redis Streams + Postgres analytics.

Canonical implementation: ``data_plane.platform`` (owned by data-plane).

Removal gate: delete this service directory and compose ``8014`` bindings when
callers have moved (rg -n '8014|data-platform' --glob '*.{yml,ts,tsx,py,md}').
"""

from data_plane.platform.app import app

__all__ = ["app"]
