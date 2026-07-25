"""Compatibility shim — canonical module is data_plane.platform.streaming.

Removal gate: delete with services/data-platform when 8014 listeners are retired.
"""

from data_plane.platform.streaming import *  # noqa: F403
