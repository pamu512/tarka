"""Ensure tests/ is on sys.path for shared helpers (e.g. aggregate_fake_redis)."""

import os
import sys
from pathlib import Path

os.environ.setdefault("OTEL_SDK_DISABLED", "1")
os.environ.setdefault("TARKA_JSON_RULES_ENGINE", "python")

if (
    not (os.environ.get("API_KEYS") or "").strip()
    and not (os.environ.get("OIDC_ISSUER") or "").strip()
):
    os.environ["ALLOW_INSECURE_NO_AUTH"] = "true"

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
