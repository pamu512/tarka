"""Entrypoint shim: ``uvicorn main:app`` and tests that ``import main``.

Rebinds this module to ``collaboration_chat_bridge.main`` so monkeypatches on
``main.settings`` / handlers hit the same objects the routes close over.
"""

from __future__ import annotations

import sys

import collaboration_chat_bridge.main as _impl

sys.modules[__name__] = _impl
