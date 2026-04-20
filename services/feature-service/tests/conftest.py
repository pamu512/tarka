"""Ensure tests/ helpers (e.g. aggregate_fake_redis) are importable."""

import os
import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

# Tests use TestClient without X-API-Key; do not inject API_KEYS (that would require a header on every call).
# Match other services: allow insecure dev auth when keys and OIDC are unset.
if not (os.environ.get("API_KEYS") or "").strip() and not (os.environ.get("OIDC_ISSUER") or "").strip():
    os.environ["ALLOW_INSECURE_NO_AUTH"] = "true"
