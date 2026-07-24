"""Entrypoint shim: ``uvicorn main:app`` — canonical package is ``graph_service``."""

from __future__ import annotations

import sys

import graph_service.main as _impl

sys.modules[__name__] = _impl
