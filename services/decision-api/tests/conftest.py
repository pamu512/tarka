"""Ensure tests/ is on sys.path for shared helpers (e.g. aggregate_fake_redis)."""

import os
import sys
from pathlib import Path

# auth_rbac middleware fails closed when API_KEYS and OIDC are unset. CI often exports
# API_KEYS="" (empty but present), so os.environ.setdefault("API_KEYS", ...) never runs.
if not (os.environ.get("API_KEYS") or "").strip() and not (os.environ.get("OIDC_ISSUER") or "").strip():
    os.environ["ALLOW_INSECURE_NO_AUTH"] = "true"

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
