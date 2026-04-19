"""Ensure tests/ helpers (e.g. aggregate_fake_redis) are importable."""

import os
import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

os.environ.setdefault("API_KEYS", "test-key")
os.environ.setdefault("ALLOW_INSECURE_NO_AUTH", "")
