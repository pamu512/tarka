"""Ensure tests/ is on sys.path for shared helpers (e.g. aggregate_fake_redis)."""
import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
