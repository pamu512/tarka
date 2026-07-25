"""data_plane.platform — Redis Streams + Postgres lite analytics (port 8014 contract)."""

from data_plane.platform.app import app, create_platform_app

__all__ = ["app", "create_platform_app"]
