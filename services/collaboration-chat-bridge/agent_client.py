"""Flat import shim for tests — same module object as the package."""

from __future__ import annotations

import sys

import collaboration_chat_bridge.agent_client as _impl

sys.modules[__name__] = _impl
