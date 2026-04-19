"""Ensure tests/ helpers (e.g. aggregate_fake_redis) are importable."""

import os
import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

# CI may set API_KEYS="" (empty string); setdefault does not override that.
if not (os.environ.get("API_KEYS") or "").strip():
    os.environ["API_KEYS"] = "test-key"
os.environ.setdefault("ALLOW_INSECURE_NO_AUTH", "")
