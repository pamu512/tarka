"""Compatibility package — prefer ``data_plane.platform``."""

from data_plane.platform.app import app, create_platform_app

__all__ = ["app", "create_platform_app"]
